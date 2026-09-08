import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

import structlog
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    PlatformAccount,
    PlatformVariant,
    Project,
    Publication,
    PublicationAttempt,
    PublicationEvent,
    PublishPackage,
)
from app.models.enums import (
    PublicationAttemptStatus,
    PublicationEventType,
    PublicationStatus,
    PublishPackageStatus,
)
from app.schemas.publishing import PublicationCreate, PublisherContext, PublishRequest
from app.services.errors import InvalidStateError, NotFoundError
from app.services.publishers.registry import PublisherRegistry
from app.services.publishing_errors import (
    AuthenticationError,
    InvalidMediaError,
    InvalidMetadataError,
    PolicyRejectedError,
    ProviderTemporaryError,
    PublisherPermissionError,
    PublishingError,
    RateLimitError,
)
from app.services.retry_policy import RetryPolicy

logger = structlog.get_logger()


class CredentialReader(Protocol):
    async def get(self, platform_account_id: uuid.UUID) -> dict[str, Any]: ...


class EmptyCredentialReader:
    async def get(self, platform_account_id: uuid.UUID) -> dict[str, Any]:
        return {}


async def aggregate_package_status(
    session: AsyncSession, package_id: uuid.UUID
) -> PublishPackageStatus | None:
    """Aggregate against every prepared variant, not only attempted platforms."""
    package = await session.get(PublishPackage, package_id)
    if package is None or package.status == PublishPackageStatus.ARCHIVED:
        return None
    variant_ids = list(
        await session.scalars(
            select(PlatformVariant.id).where(PlatformVariant.publish_package_id == package_id)
        )
    )
    publications = list(
        await session.scalars(
            select(Publication).where(Publication.publish_package_id == package_id)
        )
    )
    successes = {
        PublicationStatus.PUBLISHED,
        PublicationStatus.PUBLISHED_WITH_WARNING,
    }
    terminal_failures = {PublicationStatus.FAILED, PublicationStatus.CANCELLED}
    by_variant: dict[uuid.UUID, list[PublicationStatus]] = {
        variant_id: [] for variant_id in variant_ids
    }
    for publication in publications:
        by_variant.setdefault(publication.platform_variant_id, []).append(publication.status)

    successful_variants = {
        variant_id
        for variant_id, statuses in by_variant.items()
        if any(status in successes for status in statuses)
    }
    if variant_ids and len(successful_variants) == len(variant_ids):
        package.status = PublishPackageStatus.PUBLISHED
    elif successful_variants:
        package.status = PublishPackageStatus.PARTIALLY_PUBLISHED
    elif variant_ids and all(
        statuses and all(status in terminal_failures for status in statuses)
        for statuses in by_variant.values()
    ):
        package.status = PublishPackageStatus.FAILED
    else:
        package.status = PublishPackageStatus.READY
    return package.status


ALLOWED_TRANSITIONS: dict[PublicationStatus, set[PublicationStatus]] = {
    PublicationStatus.DRAFT: {
        PublicationStatus.SCHEDULED,
        PublicationStatus.QUEUED,
        PublicationStatus.CANCELLED,
    },
    PublicationStatus.SCHEDULED: {PublicationStatus.QUEUED, PublicationStatus.CANCELLED},
    PublicationStatus.QUEUED: {PublicationStatus.PUBLISHING, PublicationStatus.CANCELLED},
    PublicationStatus.PUBLISHING: {
        PublicationStatus.PROCESSING,
        PublicationStatus.PUBLISHED,
        PublicationStatus.PUBLISHED_WITH_WARNING,
        PublicationStatus.RETRY_WAIT,
        PublicationStatus.FAILED,
    },
    PublicationStatus.PROCESSING: {
        PublicationStatus.PUBLISHED,
        PublicationStatus.PUBLISHED_WITH_WARNING,
        PublicationStatus.RETRY_WAIT,
        PublicationStatus.FAILED,
    },
    PublicationStatus.RETRY_WAIT: {PublicationStatus.QUEUED, PublicationStatus.CANCELLED},
    PublicationStatus.FAILED: {PublicationStatus.QUEUED, PublicationStatus.CANCELLED},
    PublicationStatus.PUBLISHED: set(),
    PublicationStatus.PUBLISHED_WITH_WARNING: set(),
    PublicationStatus.CANCELLED: set(),
}


class PublicationService:
    def __init__(
        self,
        session: AsyncSession,
        registry: PublisherRegistry,
        *,
        retry_policy: RetryPolicy | None = None,
        credential_reader: CredentialReader | None = None,
        media_root: str = "/data/media",
    ) -> None:
        self.session = session
        self.registry = registry
        self.retry_policy = retry_policy or RetryPolicy()
        self.credential_reader = credential_reader or EmptyCredentialReader()
        self.media_root = Path(media_root)

    async def create(self, data: PublicationCreate) -> Publication:
        if data.idempotency_key:
            existing = await self.session.scalar(
                select(Publication).where(Publication.idempotency_key == data.idempotency_key)
            )
            if existing is not None:
                return existing
        variant = await self.session.get(PlatformVariant, data.platform_variant_id)
        account = await self.session.get(PlatformAccount, data.platform_account_id)
        if variant is None or account is None:
            raise NotFoundError("PlatformVariant or PlatformAccount not found")
        package = await self.session.get(PublishPackage, variant.publish_package_id)
        if package is None:
            raise NotFoundError("PublishPackage not found")
        if account.project_id != package.project_id or account.platform != variant.platform:
            raise InvalidStateError("Account, variant and package do not match")
        if not account.is_active:
            raise InvalidStateError("PlatformAccount is inactive")
        project = await self.session.get(Project, package.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        now = datetime.now(UTC)
        scheduled_at = self._utc(data.scheduled_at)
        if scheduled_at and scheduled_at <= now and not data.publish_now:
            raise InvalidStateError("scheduled_at must be in the future")
        status = (
            PublicationStatus.QUEUED
            if data.publish_now
            else PublicationStatus.SCHEDULED
            if scheduled_at
            else PublicationStatus.DRAFT
        )
        snapshot = self._snapshot(variant)
        media_hash = self._media_hash(variant.video_path or variant.thumbnail_path)
        publication = Publication(
            publish_package_id=package.id,
            platform_variant_id=variant.id,
            platform_account_id=account.id,
            platform=variant.platform,
            status=status,
            scheduled_at=scheduled_at,
            publication_metadata={**data.metadata, "timezone": project.timezone},
            variant_snapshot=snapshot,
            variant_hash=variant.content_hash,
            media_hash=media_hash,
            idempotency_key=data.idempotency_key,
        )
        self.session.add(publication)
        try:
            await self.session.flush()
            self._event(
                publication, PublicationEventType.CREATED, {"variant_revision": variant.revision}
            )
            if status == PublicationStatus.SCHEDULED:
                self._event(
                    publication,
                    PublicationEventType.SCHEDULED,
                    {"scheduled_at": scheduled_at.isoformat() if scheduled_at else None},
                )
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            if data.idempotency_key:
                existing = await self.session.scalar(
                    select(Publication).where(Publication.idempotency_key == data.idempotency_key)
                )
                if existing is not None:
                    return existing
            raise
        await self.session.refresh(publication)
        return publication

    async def fail_preflight(
        self, publication_id: uuid.UUID, *, code: str, message: str
    ) -> Publication:
        publication = await self.get(publication_id)
        if publication.status == PublicationStatus.FAILED and publication.remote_id is None:
            return publication
        if publication.status in {
            PublicationStatus.PUBLISHED,
            PublicationStatus.PUBLISHED_WITH_WARNING,
            PublicationStatus.CANCELLED,
        }:
            return publication
        if publication.status not in {
            PublicationStatus.DRAFT,
            PublicationStatus.SCHEDULED,
            PublicationStatus.QUEUED,
        }:
            raise InvalidStateError("Publication can no longer fail preflight")
        publication.status = PublicationStatus.FAILED
        publication.next_retry_at = None
        publication.task_id = None
        publication.last_error_code = code
        publication.last_error_message = message
        self._event(
            publication,
            PublicationEventType.FAILED,
            {"stage": "preflight", "error_code": code},
        )
        await self._update_package_status(publication.publish_package_id)
        await self.session.commit()
        await self.session.refresh(publication)
        return publication

    async def get(self, publication_id: uuid.UUID) -> Publication:
        publication = await self.session.get(Publication, publication_id)
        if publication is None:
            raise NotFoundError("Publication not found")
        return publication

    async def list(
        self,
        *,
        status: PublicationStatus | None = None,
        package_id: uuid.UUID | None = None,
        limit: int = 100,
    ) -> Sequence[Publication]:
        query = select(Publication)
        if status:
            query = query.where(Publication.status == status)
        if package_id:
            query = query.where(Publication.publish_package_id == package_id)
        return (
            await self.session.scalars(
                query.order_by(Publication.created_at.desc()).limit(min(limit, 500))
            )
        ).all()

    async def schedule(self, publication_id: uuid.UUID, scheduled_at: datetime) -> Publication:
        publication = await self.get(publication_id)
        if publication.status not in {
            PublicationStatus.DRAFT,
            PublicationStatus.SCHEDULED,
            PublicationStatus.FAILED,
            PublicationStatus.RETRY_WAIT,
        }:
            raise InvalidStateError("Publication can no longer be rescheduled")
        target = self._utc(scheduled_at)
        if target is None or target <= datetime.now(UTC):
            raise InvalidStateError("scheduled_at must be in the future")
        publication.status = PublicationStatus.SCHEDULED
        publication.scheduled_at = target
        publication.next_retry_at = None
        publication.task_id = None
        publication.last_error_code = None
        publication.last_error_message = None
        self._event(
            publication, PublicationEventType.SCHEDULED, {"scheduled_at": target.isoformat()}
        )
        await self.session.commit()
        await self.session.refresh(publication)
        return publication

    async def publish_now(self, publication_id: uuid.UUID) -> tuple[Publication, bool]:
        publication = await self.get(publication_id)
        if publication.status == PublicationStatus.QUEUED and publication.task_id:
            return publication, False
        if publication.remote_id or publication.status in {
            PublicationStatus.PUBLISHED,
            PublicationStatus.PUBLISHED_WITH_WARNING,
            PublicationStatus.PUBLISHING,
            PublicationStatus.PROCESSING,
        }:
            return publication, False
        if publication.status == PublicationStatus.CANCELLED:
            raise InvalidStateError("Cancelled publication cannot be published")
        publication.status = PublicationStatus.QUEUED
        publication.scheduled_at = None
        publication.next_retry_at = None
        publication.task_id = None
        await self.session.commit()
        await self.session.refresh(publication)
        return publication, True

    async def cancel(self, publication_id: uuid.UUID) -> Publication:
        existing = await self.get(publication_id)
        if existing.status == PublicationStatus.CANCELLED:
            return existing
        result = await self.session.execute(
            update(Publication)
            .where(
                Publication.id == publication_id,
                Publication.status.in_(
                    [
                        PublicationStatus.DRAFT,
                        PublicationStatus.SCHEDULED,
                        PublicationStatus.QUEUED,
                        PublicationStatus.RETRY_WAIT,
                        PublicationStatus.FAILED,
                    ]
                ),
                Publication.remote_id.is_(None),
            )
            .values(status=PublicationStatus.CANCELLED, next_retry_at=None)
            .returning(Publication.id)
        )
        if result.scalar_one_or_none() is None:
            publication = await self.get(publication_id)
            raise InvalidStateError(f"Cannot cancel publication in {publication.status.value}")
        publication = await self.get(publication_id)
        self._event(publication, PublicationEventType.CANCELLED)
        await self._update_package_status(publication.publish_package_id)
        await self.session.commit()
        await self.session.refresh(publication)
        return publication

    async def manual_retry(self, publication_id: uuid.UUID) -> tuple[Publication, bool]:
        publication = await self.get(publication_id)
        if publication.status == PublicationStatus.QUEUED:
            return publication, False
        if publication.remote_id:
            return publication, False
        if publication.status not in {PublicationStatus.FAILED, PublicationStatus.RETRY_WAIT}:
            raise InvalidStateError("Only a failed publication can be retried")
        publication.status = PublicationStatus.QUEUED
        publication.next_retry_at = None
        publication.task_id = None
        publication.last_error_code = None
        publication.last_error_message = None
        self._event(publication, PublicationEventType.RETRIED, {"manual": True})
        await self.session.commit()
        await self.session.refresh(publication)
        return publication, True

    async def update_scheduled_content(
        self, publication_id: uuid.UUID, updates: dict[str, Any]
    ) -> Publication:
        publication = await self.get(publication_id)
        if (
            publication.status
            not in {
                PublicationStatus.DRAFT,
                PublicationStatus.SCHEDULED,
                PublicationStatus.QUEUED,
            }
            or publication.remote_id
        ):
            raise InvalidStateError("Publication input is already immutable")
        variant = await self.session.get(PlatformVariant, publication.platform_variant_id)
        account = await self.session.get(PlatformAccount, publication.platform_account_id)
        if variant is None or account is None:
            raise NotFoundError("Publication dependencies not found")
        for field in ("title", "caption", "description", "hashtags", "settings"):
            if field in updates and updates[field] is not None:
                setattr(variant, field, updates[field])
        variant.revision += 1
        variant_payload = {
            "title": variant.title,
            "caption": variant.caption,
            "description": variant.description,
            "hashtags": variant.hashtags,
            "settings": variant.settings,
            "video_path": variant.video_path,
            "thumbnail_path": variant.thumbnail_path,
        }
        variant.content_hash = hashlib.sha256(
            json.dumps(variant_payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        publication.variant_snapshot = self._snapshot(variant)
        publication.variant_hash = variant.content_hash
        publication.media_hash = self._media_hash(variant.video_path or variant.thumbnail_path)
        credentials = await self.credential_reader.get(account.id)
        context = PublisherContext(
            account_id=account.id,
            external_account_id=account.external_account_id,
            username=account.username,
            settings=account.settings,
            capabilities=account.capabilities,
            credentials=credentials,
        )
        validation = await self.registry.get(publication.platform).validate(
            self._request(publication), context
        )
        if not validation.ready:
            await self.session.rollback()
            message = "; ".join(issue.message for issue in validation.issues)
            raise InvalidStateError(message or "Platform validation failed")
        await self.session.commit()
        await self.session.refresh(publication)
        return publication

    async def claim_for_publish(self, publication_id: uuid.UUID) -> Publication | None:
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(Publication)
            .where(
                Publication.id == publication_id,
                Publication.status == PublicationStatus.QUEUED,
                Publication.remote_id.is_(None),
            )
            .values(
                status=PublicationStatus.PUBLISHING,
                claimed_at=now,
                started_at=now,
                task_id=None,
            )
            .returning(Publication.id)
        )
        claimed_id = result.scalar_one_or_none()
        if claimed_id is None:
            await self.session.rollback()
            return None
        await self.session.commit()
        publication = await self.get(claimed_id)
        self._event(publication, PublicationEventType.CLAIMED)
        await self.session.commit()
        return publication

    async def execute(self, publication_id: uuid.UUID) -> Publication:
        publication = await self.claim_for_publish(publication_id)
        if publication is None:
            return await self.get(publication_id)
        account = await self.session.get(PlatformAccount, publication.platform_account_id)
        if account is None:
            raise NotFoundError("PlatformAccount not found")
        publication.attempt_count += 1
        attempt = PublicationAttempt(
            publication_id=publication.id,
            attempt_number=publication.attempt_count,
            status=PublicationAttemptStatus.STARTED,
            media_hash=publication.media_hash,
            attempt_metadata={"variant_hash": publication.variant_hash},
        )
        self.session.add(attempt)
        self._event(publication, PublicationEventType.UPLOAD_STARTED)
        await self.session.commit()
        credentials = await self.credential_reader.get(account.id)
        request = self._request(publication)
        context = PublisherContext(
            account_id=account.id,
            external_account_id=account.external_account_id,
            username=account.username,
            settings=account.settings,
            capabilities=account.capabilities,
            credentials=credentials,
        )
        try:
            publisher = self.registry.get(publication.platform)
            validation = await publisher.validate(request, context)
            if not validation.ready:
                issue = next((item for item in validation.issues if item.severity == "error"), None)
                raise self._validation_error(
                    issue.code if issue else "INVALID_METADATA",
                    issue.message if issue else "Preflight validation failed",
                )
            result = await publisher.publish(request, context)
            finished = datetime.now(UTC)
            publication.remote_id = result.remote_id
            publication.remote_url = result.remote_url
            publication.publication_metadata = {
                **publication.publication_metadata,
                "provider": result.provider_metadata,
                **({"warning": result.warning} if result.warning else {}),
            }
            attempt.finished_at = finished
            attempt.provider_request_id = result.provider_request_id
            attempt.attempt_metadata = {
                **attempt.attempt_metadata,
                "provider": result.provider_metadata,
            }
            if result.status == "processing":
                publication.status = PublicationStatus.PROCESSING
                publication.next_retry_at = finished + timedelta(minutes=1)
                attempt.status = PublicationAttemptStatus.PROCESSING
                self._event(publication, PublicationEventType.REMOTE_ACCEPTED)
                self._event(publication, PublicationEventType.PROCESSING)
            else:
                publication.status = (
                    PublicationStatus.PUBLISHED_WITH_WARNING
                    if result.status == "published_with_warning"
                    else PublicationStatus.PUBLISHED
                )
                publication.published_at = finished
                publication.next_retry_at = None
                attempt.status = PublicationAttemptStatus.SUCCEEDED
                self._event(publication, PublicationEventType.REMOTE_ACCEPTED)
                self._event(publication, PublicationEventType.PUBLISHED)
            publication.last_error_code = None
            publication.last_error_message = None
        except PublishingError as exc:
            await self._record_failure(publication, attempt, exc)
        except Exception as exc:
            await logger.aexception(
                "publication_provider_unexpected_error",
                publication_id=str(publication.id),
                platform=publication.platform.value,
                error_type=type(exc).__name__,
            )
            await self._record_failure(
                publication, attempt, ProviderTemporaryError("Unexpected provider failure")
            )
        await self._update_package_status(publication.publish_package_id)
        await self.session.commit()
        await self.session.refresh(publication)
        return publication

    async def poll_status(self, publication_id: uuid.UUID) -> Publication:
        publication = await self.get(publication_id)
        if publication.status != PublicationStatus.PROCESSING or not publication.remote_id:
            return publication
        account = await self.session.get(PlatformAccount, publication.platform_account_id)
        if account is None:
            raise NotFoundError("PlatformAccount not found")
        credentials = await self.credential_reader.get(account.id)
        context = PublisherContext(
            account_id=account.id,
            external_account_id=account.external_account_id,
            username=account.username,
            settings=account.settings,
            capabilities=account.capabilities,
            credentials=credentials,
        )
        request = self._request(publication)
        try:
            result = await self.registry.get(publication.platform).get_status(request, context)
            publication.publication_metadata = {
                **publication.publication_metadata,
                "provider": result.provider_metadata,
            }
            if result.status == "processing":
                publication.next_retry_at = datetime.now(UTC) + timedelta(minutes=2)
            elif result.status == "published":
                publication.status = (
                    PublicationStatus.PUBLISHED_WITH_WARNING
                    if publication.publication_metadata.get("warning")
                    else PublicationStatus.PUBLISHED
                )
                publication.published_at = datetime.now(UTC)
                publication.remote_url = result.remote_url or publication.remote_url
                publication.next_retry_at = None
                attempt = await self.session.scalar(
                    select(PublicationAttempt)
                    .where(PublicationAttempt.publication_id == publication.id)
                    .order_by(PublicationAttempt.attempt_number.desc())
                    .limit(1)
                )
                if attempt and attempt.status == PublicationAttemptStatus.PROCESSING:
                    attempt.status = PublicationAttemptStatus.SUCCEEDED
                self._event(publication, PublicationEventType.PUBLISHED)
            else:
                publication.status = PublicationStatus.FAILED
                publication.last_error_code = result.error_code or "PROCESSING_FAILED"
                publication.last_error_message = result.error_message or "Обработка не завершилась."
                publication.next_retry_at = None
                self._event(
                    publication,
                    PublicationEventType.FAILED,
                    {"error_code": publication.last_error_code},
                )
        except PublishingError as exc:
            publication.last_error_code = exc.code
            publication.last_error_message = exc.user_message
            publication.next_retry_at = (
                datetime.now(UTC) + timedelta(minutes=2) if exc.retryable else None
            )
            if not exc.retryable:
                publication.status = PublicationStatus.FAILED
        await self._update_package_status(publication.publish_package_id)
        await self.session.commit()
        await self.session.refresh(publication)
        return publication

    async def mark_task_enqueued(self, publication_id: uuid.UUID, task_id: str) -> None:
        await self.session.execute(
            update(Publication)
            .where(
                Publication.id == publication_id,
                Publication.status == PublicationStatus.QUEUED,
            )
            .values(task_id=task_id)
        )
        await self.session.commit()

    async def recover_stale_claims(self, *, older_than_seconds: int = 1800) -> int:
        cutoff = datetime.now(UTC) - timedelta(seconds=older_than_seconds)
        rows = (
            await self.session.scalars(
                select(Publication).where(
                    Publication.status == PublicationStatus.PUBLISHING,
                    Publication.claimed_at < cutoff,
                    Publication.remote_id.is_(None),
                )
            )
        ).all()
        for item in rows:
            item.status = PublicationStatus.FAILED
            item.last_error_code = "AMBIGUOUS_PROVIDER_STATE"
            item.last_error_message = (
                "Worker stopped during upload; manual verification is required before retry."
            )
            self._event(item, PublicationEventType.FAILED, {"ambiguous": True})
        await self.session.commit()
        return len(rows)

    async def _record_failure(
        self,
        publication: Publication,
        attempt: PublicationAttempt,
        error: PublishingError,
    ) -> None:
        now = datetime.now(UTC)
        decision = self.retry_policy.decide(publication.attempt_count, error, now=now)
        publication.last_error_code = error.code
        publication.last_error_message = error.user_message
        if error.provider_metadata:
            publication.publication_metadata = {
                **publication.publication_metadata,
                "provider": {
                    **publication.publication_metadata.get("provider", {}),
                    **error.provider_metadata,
                },
            }
        attempt.finished_at = now
        attempt.provider_error_code = error.provider_code
        attempt.sanitized_error = error.user_message
        self._event(
            publication,
            PublicationEventType.FAILED,
            {"error_code": error.code, "retryable": error.retryable},
        )
        if decision.retry:
            publication.status = PublicationStatus.RETRY_WAIT
            publication.next_retry_at = decision.retry_at
            attempt.status = PublicationAttemptStatus.RETRY_SCHEDULED
            self._event(
                publication,
                PublicationEventType.RETRIED,
                {"retry_at": decision.retry_at.isoformat() if decision.retry_at else None},
            )
        else:
            publication.status = PublicationStatus.FAILED
            publication.next_retry_at = None
            attempt.status = PublicationAttemptStatus.FAILED

    async def _update_package_status(self, package_id: uuid.UUID) -> None:
        await aggregate_package_status(self.session, package_id)

    def _request(self, publication: Publication) -> PublishRequest:
        snapshot = publication.variant_snapshot
        return PublishRequest(
            publication_id=publication.id,
            platform=publication.platform,
            video_path=self._resolved(snapshot.get("video_path")),
            thumbnail_path=self._resolved(snapshot.get("thumbnail_path")),
            title=str(snapshot.get("title", "")),
            caption=str(snapshot.get("caption", "")),
            description=str(snapshot.get("description", "")),
            hashtags=list(snapshot.get("hashtags", [])),
            settings=dict(snapshot.get("settings", {})),
            media_hash=publication.media_hash,
            remote_id=publication.remote_id,
            provider_metadata=dict(publication.publication_metadata.get("provider", {})),
        )

    @staticmethod
    def _validation_error(code: str, message: str) -> PublishingError:
        error_type = {
            "AUTH_REQUIRED": AuthenticationError,
            "PERMISSION_DENIED": PublisherPermissionError,
            "INVALID_MEDIA": InvalidMediaError,
            "POLICY_REJECTED": PolicyRejectedError,
            "RATE_LIMIT": RateLimitError,
            "PROVIDER_TEMPORARY": ProviderTemporaryError,
        }.get(code, InvalidMetadataError)
        return error_type(message, provider_code=code)

    @staticmethod
    def _snapshot(variant: PlatformVariant) -> dict[str, Any]:
        return {
            "variant_id": str(variant.id),
            "revision": variant.revision,
            "platform": variant.platform.value,
            "video_path": variant.video_path,
            "thumbnail_path": variant.thumbnail_path,
            "title": variant.title,
            "caption": variant.caption,
            "description": variant.description,
            "hashtags": list(variant.hashtags),
            "settings": dict(variant.settings),
            "media_profile": dict(variant.media_profile),
        }

    def _media_hash(self, value: str | None) -> str | None:
        path = Path(self._resolved(value) or "")
        if not value or not path.is_file():
            return None
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    def _resolved(self, value: Any) -> str | None:
        if not value:
            return None
        path = Path(str(value))
        return str(path if path.is_absolute() else self.media_root / path)

    def _event(
        self,
        publication: Publication,
        event_type: PublicationEventType,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.session.add(
            PublicationEvent(
                publication_id=publication.id,
                event_type=event_type,
                details=details or {},
            )
        )

    @staticmethod
    def _utc(value: datetime | None) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise InvalidStateError("Datetime must be timezone-aware")
        return value.astimezone(UTC)
