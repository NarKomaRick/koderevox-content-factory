import hashlib
import hmac
import json
import time
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PlatformAccount, Publication, PublicationEvent, WebhookReceipt
from app.models.enums import (
    PublicationEventType,
    PublicationStatus,
    PublishingPlatform,
)
from app.services.errors import InvalidStateError
from app.services.publications import aggregate_package_status


class TikTokWebhookService:
    def __init__(
        self,
        session: AsyncSession,
        client_key: str,
        client_secret: str,
        *,
        tolerance_seconds: int = 300,
    ) -> None:
        self.session = session
        self.client_key = client_key
        self.client_secret = client_secret
        self.tolerance_seconds = tolerance_seconds

    async def handle(self, raw_body: bytes, signature_header: str) -> bool:
        self._verify(raw_body, signature_header)
        try:
            payload = json.loads(raw_body)
            content = json.loads(payload.get("content") or "{}")
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            raise InvalidStateError("Invalid TikTok webhook payload") from exc
        if payload.get("client_key") != self.client_key:
            raise InvalidStateError("TikTok client_key mismatch")
        event = str(payload.get("event", ""))
        publish_id = str(content.get("publish_id", ""))
        event_id = hashlib.sha256(
            f"{event}:{payload.get('create_time')}:{payload.get('user_openid')}:{payload.get('content')}".encode()
        ).hexdigest()
        self.session.add(
            WebhookReceipt(
                platform=PublishingPlatform.TIKTOK,
                external_event_id=event_id,
                payload_hash=hashlib.sha256(raw_body).hexdigest(),
            )
        )
        try:
            await self.session.flush()
        except IntegrityError:
            await self.session.rollback()
            return False
        publication = await self.session.scalar(
            select(Publication).where(
                Publication.platform == PublishingPlatform.TIKTOK,
                Publication.remote_id == publish_id,
            )
        )
        if publication is not None:
            if event in {"post.publish.complete", "post.publish.publicly_available"}:
                publication.status = PublicationStatus.PUBLISHED
                publication.published_at = datetime.now(UTC)
                publication.next_retry_at = None
                post_id = content.get("post_id")
                account = await self.session.get(PlatformAccount, publication.platform_account_id)
                username = str(account.username or "").lstrip("@") if account else ""
                if post_id and username:
                    publication.remote_url = f"https://www.tiktok.com/@{username}/video/{post_id}"
                self.session.add(
                    PublicationEvent(
                        publication_id=publication.id,
                        event_type=PublicationEventType.PUBLISHED,
                        details={"source": "tiktok_webhook", "event": event},
                    )
                )
            elif event == "post.publish.failed":
                publication.status = PublicationStatus.FAILED
                publication.last_error_code = str(content.get("reason", "TIKTOK_FAILED"))
                publication.last_error_message = "TikTok processing failed."
                publication.next_retry_at = None
                self.session.add(
                    PublicationEvent(
                        publication_id=publication.id,
                        event_type=PublicationEventType.FAILED,
                        details={"source": "tiktok_webhook", "event": event},
                    )
                )
            await self._update_package(publication.publish_package_id)
        await self.session.commit()
        return True

    async def _update_package(self, package_id) -> None:
        await aggregate_package_status(self.session, package_id)

    def _verify(self, body: bytes, header: str) -> None:
        parts = dict(item.split("=", 1) for item in header.split(",") if "=" in item)
        try:
            timestamp = int(parts["t"])
            signature = parts["s"]
        except (KeyError, ValueError) as exc:
            raise InvalidStateError("TikTok signature is missing") from exc
        if abs(int(time.time()) - timestamp) > self.tolerance_seconds:
            raise InvalidStateError("TikTok webhook timestamp is stale")
        signed = str(timestamp).encode() + b"." + body
        expected = hmac.new(self.client_secret.encode(), signed, hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise InvalidStateError("TikTok webhook signature is invalid")
