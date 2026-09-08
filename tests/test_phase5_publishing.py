import random
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.ai.mock import MockAIProvider
from app.models import (
    ContentDraft,
    ContentIdea,
    PlatformAccount,
    PublicationAttempt,
    SourceItem,
    User,
    VideoProject,
)
from app.models.enums import (
    ContentFormat,
    ContentPillar,
    DraftStatus,
    IdeaStatus,
    Platform,
    ProcessingStage,
    PublicationStatus,
    PublishingPlatform,
    PublishPackageStatus,
    SourceStatus,
    SourceType,
    UserRole,
    VideoProjectStatus,
)
from app.schemas.publishing import (
    PlatformValidationResult,
    ProviderStatusResult,
    PublicationCreate,
    PublisherContext,
    PublishRequest,
    PublishResult,
)
from app.services.platform_adaptation import PlatformAdaptationService
from app.services.platform_variant_media import PlatformVariantMediaService
from app.services.publication_scheduler import PublicationScheduler
from app.services.publications import PublicationService
from app.services.publishers.registry import PublisherRegistry
from app.services.publishers.telegram import TelegramPublisher
from app.services.publishing_errors import InvalidMetadataError, ProviderTemporaryError
from app.services.retry_policy import RetryPolicy


class FakePublisher:
    def __init__(self, outcomes: list[object] | None = None) -> None:
        self.outcomes = outcomes or []
        self.calls = 0

    async def validate(self, request: PublishRequest, context: PublisherContext):
        return PlatformValidationResult(platform=request.platform, ready=True)

    async def publish(self, request: PublishRequest, context: PublisherContext):
        self.calls += 1
        if self.outcomes:
            outcome = self.outcomes.pop(0)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome
        return PublishResult(remote_id=f"remote-{request.publication_id}")

    async def get_status(self, request: PublishRequest, context: PublisherContext):
        raise NotImplementedError

    async def delete(self, request: PublishRequest, context: PublisherContext):
        return None


class ProcessingPublisher(FakePublisher):
    def __init__(self, final_status: str = "published") -> None:
        super().__init__()
        self.final_status = final_status

    async def publish(self, request: PublishRequest, context: PublisherContext):
        self.calls += 1
        return PublishResult(remote_id=f"remote-{request.platform.value}", status="processing")

    async def get_status(self, request: PublishRequest, context: PublisherContext):
        return ProviderStatusResult(
            status=self.final_status,
            remote_id=request.remote_id,
            remote_url=f"https://example.test/{request.remote_id}",
            error_code="PROCESSING_FAILED" if self.final_status == "failed" else None,
        )


async def approved_video(session, tmp_path: Path) -> VideoProject:
    project = await session.scalar(select(__import__("app.models", fromlist=["Project"]).Project))
    user = User(telegram_id=991, username="owner", role=UserRole.ADMIN)
    session.add(user)
    await session.flush()
    source = SourceItem(
        project_id=project.id,
        user_id=user.id,
        type=SourceType.VIDEO,
        transcript="Приложение отправляло запрос дважды при возврате на экран.",
        processing_status=SourceStatus.READY,
        processing_stage=ProcessingStage.READY,
        content_analysis={
            "source_facts": ["Запрос повторялся при возврате на экран"],
            "key_points": ["Нужна идемпотентность"],
        },
        topic="Двойной REST-запрос",
    )
    session.add(source)
    await session.flush()
    idea = ContentIdea(
        project_id=project.id,
        source_item_id=source.id,
        title="Двойной запрос",
        description="Разбор бага",
        angle="Технический разбор",
        suggested_hook="Почему запрос ушёл дважды",
        suggested_format=ContentFormat.SHORT_VIDEO,
        estimated_duration=30,
        target_audience="Разработчики",
        content_pillar=ContentPillar.EDUCATION,
        status=IdeaStatus.SELECTED,
    )
    session.add(idea)
    await session.flush()
    draft = ContentDraft(
        idea_id=idea.id,
        platform=Platform.YOUTUBE_SHORTS,
        format=ContentFormat.SHORT_VIDEO,
        hook="Почему запрос ушёл дважды",
        script="При возврате на экран приложение повторяло запрос.",
        caption="Разбираем двойной запрос",
        title="Почему приложение отправляло запрос дважды",
        description="Технический разбор жизненного цикла экрана.",
        call_to_action="Проверьте lifecycle.",
        estimated_duration=30,
        status=DraftStatus.APPROVED,
    )
    session.add(draft)
    await session.flush()
    video_file = tmp_path / "approved.mp4"
    video_file.write_bytes(b"safe-approved-video")
    video = VideoProject(
        project_id=project.id,
        source_item_id=source.id,
        content_draft_id=draft.id,
        status=VideoProjectStatus.APPROVED,
        final_path=str(video_file),
        render_fingerprint="a" * 64,
        edit_plan={"hook_text": draft.hook},
    )
    session.add(video)
    await session.commit()
    await session.refresh(video)
    return video


async def prepared(session, tmp_path: Path):
    video = await approved_video(session, tmp_path)
    service = PlatformAdaptationService(session, MockAIProvider())
    package, variants = await service.prepare_package(video.id, list(PublishingPlatform))
    accounts = []
    for platform in PublishingPlatform:
        account = PlatformAccount(
            project_id=video.project_id,
            platform=platform,
            display_name=platform.value,
            external_account_id="@test_channel"
            if platform == PublishingPlatform.TELEGRAM
            else None,
            settings={"chat_id": "@test_channel"}
            if platform == PublishingPlatform.TELEGRAM
            else {},
        )
        session.add(account)
        accounts.append(account)
    await session.commit()
    for account in accounts:
        await session.refresh(account)
    return (
        package,
        {item.platform: item for item in variants},
        {item.platform: item for item in accounts},
    )


@pytest.mark.asyncio
async def test_platform_adaptations_are_distinct_and_idempotent(session, tmp_path: Path):
    video = await approved_video(session, tmp_path)
    service = PlatformAdaptationService(session, MockAIProvider())
    package, variants = await service.prepare_package(video.id, list(PublishingPlatform))
    assert package.status == PublishPackageStatus.READY
    assert len({item.caption for item in variants}) == 3
    assert (
        next(item for item in variants if item.platform == PublishingPlatform.TIKTOK).settings[
            "render_overrides"
        ]["watermark_enabled"]
        is False
    )
    same_package, same_variants = await service.prepare_package(video.id, list(PublishingPlatform))
    assert same_package.id == package.id
    assert {item.id for item in same_variants} == {item.id for item in variants}


@pytest.mark.asyncio
async def test_tiktok_clean_derivative_reuses_approved_plans_without_ai(session, tmp_path: Path):
    video = await approved_video(session, tmp_path)
    video.edit_plan = {"clips": [{"source_start": 0, "source_end": 10}], "hook_text": "Hook"}
    video.visual_plan = {"insertions": []}
    video.render_settings = {"watermark_enabled": True, "width": 1080, "height": 1920}
    project = await session.get(
        __import__("app.models", fromlist=["Project"]).Project, video.project_id
    )
    project.brand_preset = {"watermark_enabled": True, "logo_path": "logo.png"}
    await session.commit()
    _, variants = await PlatformAdaptationService(session, MockAIProvider()).prepare_package(
        video.id, [PublishingPlatform.TIKTOK]
    )
    variant = variants[0]
    assert variant.video_path is None
    assert variant.settings["requires_rerender"] is True
    _, derivative = await PlatformVariantMediaService(session).prepare_tiktok_derivative(variant.id)
    assert derivative is not None
    assert derivative.edit_plan == video.edit_plan
    assert derivative.visual_plan == video.visual_plan
    assert derivative.render_settings["watermark_enabled"] is False
    assert derivative.render_settings["branding_enabled"] is False


@pytest.mark.asyncio
async def test_publication_freezes_variant_and_media_hash(session, tmp_path: Path):
    package, variants, accounts = await prepared(session, tmp_path)
    publisher = FakePublisher()
    registry = PublisherRegistry()
    registry.register(PublishingPlatform.TELEGRAM, publisher)
    service = PublicationService(session, registry)
    variant = variants[PublishingPlatform.TELEGRAM]
    publication = await service.create(
        PublicationCreate(
            platform_variant_id=variant.id,
            platform_account_id=accounts[PublishingPlatform.TELEGRAM].id,
            scheduled_at=datetime.now(UTC) + timedelta(hours=1),
        )
    )
    frozen_caption = publication.variant_snapshot["caption"]
    assert publication.media_hash is not None
    variant.caption = "Изменённый master после scheduling"
    await session.commit()
    await session.refresh(publication)
    assert publication.variant_snapshot["caption"] == frozen_caption
    assert publication.publish_package_id == package.id


@pytest.mark.asyncio
async def test_duplicate_delivery_publishes_only_once(session, tmp_path: Path):
    _, variants, accounts = await prepared(session, tmp_path)
    publisher = FakePublisher()
    registry = PublisherRegistry()
    registry.register(PublishingPlatform.TELEGRAM, publisher)
    service = PublicationService(session, registry)
    publication = await service.create(
        PublicationCreate(
            platform_variant_id=variants[PublishingPlatform.TELEGRAM].id,
            platform_account_id=accounts[PublishingPlatform.TELEGRAM].id,
            publish_now=True,
            idempotency_key="button-123",
        )
    )
    duplicate = await service.create(
        PublicationCreate(
            platform_variant_id=variants[PublishingPlatform.TELEGRAM].id,
            platform_account_id=accounts[PublishingPlatform.TELEGRAM].id,
            publish_now=True,
            idempotency_key="button-123",
        )
    )
    assert duplicate.id == publication.id
    assert (await service.execute(publication.id)).status == PublicationStatus.PUBLISHED
    assert (await service.execute(publication.id)).status == PublicationStatus.PUBLISHED
    assert publisher.calls == 1
    assert await session.scalar(select(func.count(PublicationAttempt.id))) == 1


@pytest.mark.asyncio
async def test_scheduler_queues_only_due_and_ignores_cancelled(session, tmp_path: Path):
    _, variants, accounts = await prepared(session, tmp_path)
    registry = PublisherRegistry()
    service = PublicationService(session, registry)
    variant = variants[PublishingPlatform.TELEGRAM]
    account = accounts[PublishingPlatform.TELEGRAM]
    future = await service.create(
        PublicationCreate(
            platform_variant_id=variant.id,
            platform_account_id=account.id,
            scheduled_at=datetime.now(UTC) + timedelta(days=1),
        )
    )
    due = await service.create(
        PublicationCreate(
            platform_variant_id=variant.id,
            platform_account_id=account.id,
        )
    )
    due.status = PublicationStatus.SCHEDULED
    due.scheduled_at = datetime.now(UTC) - timedelta(seconds=1)
    cancelled = await service.create(
        PublicationCreate(
            platform_variant_id=variant.id,
            platform_account_id=account.id,
        )
    )
    cancelled.status = PublicationStatus.CANCELLED
    cancelled.scheduled_at = datetime.now(UTC) - timedelta(seconds=1)
    await session.commit()
    claimed = await PublicationScheduler(session).claim_due()
    assert claimed == [due.id]
    assert (await service.get(future.id)).status == PublicationStatus.SCHEDULED
    assert (await service.get(cancelled.id)).status == PublicationStatus.CANCELLED


@pytest.mark.asyncio
async def test_temporary_error_retries_and_keeps_attempt_history(session, tmp_path: Path):
    _, variants, accounts = await prepared(session, tmp_path)
    publisher = FakePublisher([ProviderTemporaryError(), PublishResult(remote_id="chat:42")])
    registry = PublisherRegistry()
    registry.register(PublishingPlatform.TELEGRAM, publisher)
    service = PublicationService(
        session,
        registry,
        retry_policy=RetryPolicy(
            max_attempts=2,
            delays_seconds=[1],
            jitter_ratio=0,
            random_source=random.Random(1),
        ),
    )
    publication = await service.create(
        PublicationCreate(
            platform_variant_id=variants[PublishingPlatform.TELEGRAM].id,
            platform_account_id=accounts[PublishingPlatform.TELEGRAM].id,
            publish_now=True,
        )
    )
    assert (await service.execute(publication.id)).status == PublicationStatus.RETRY_WAIT
    publication.status = PublicationStatus.QUEUED
    await session.commit()
    assert (await service.execute(publication.id)).status == PublicationStatus.PUBLISHED
    attempts = list(
        await session.scalars(
            select(PublicationAttempt).order_by(PublicationAttempt.attempt_number)
        )
    )
    assert [item.status.value for item in attempts] == ["retry_scheduled", "succeeded"]


@pytest.mark.asyncio
async def test_permanent_error_does_not_retry(session, tmp_path: Path):
    _, variants, accounts = await prepared(session, tmp_path)
    publisher = FakePublisher([InvalidMetadataError()])
    registry = PublisherRegistry()
    registry.register(PublishingPlatform.TELEGRAM, publisher)
    service = PublicationService(session, registry)
    publication = await service.create(
        PublicationCreate(
            platform_variant_id=variants[PublishingPlatform.TELEGRAM].id,
            platform_account_id=accounts[PublishingPlatform.TELEGRAM].id,
            publish_now=True,
        )
    )
    result = await service.execute(publication.id)
    assert result.status == PublicationStatus.FAILED
    assert result.last_error_code == "INVALID_METADATA"
    assert result.next_retry_at is None


@pytest.mark.asyncio
async def test_platform_failure_does_not_undo_other_success(session, tmp_path: Path):
    package, variants, accounts = await prepared(session, tmp_path)
    registry = PublisherRegistry()
    registry.register(PublishingPlatform.TELEGRAM, FakePublisher())
    registry.register(PublishingPlatform.YOUTUBE, FakePublisher([InvalidMetadataError()]))
    service = PublicationService(session, registry)
    telegram = await service.create(
        PublicationCreate(
            platform_variant_id=variants[PublishingPlatform.TELEGRAM].id,
            platform_account_id=accounts[PublishingPlatform.TELEGRAM].id,
            publish_now=True,
        )
    )
    youtube = await service.create(
        PublicationCreate(
            platform_variant_id=variants[PublishingPlatform.YOUTUBE].id,
            platform_account_id=accounts[PublishingPlatform.YOUTUBE].id,
            publish_now=True,
        )
    )
    assert (await service.execute(telegram.id)).status == PublicationStatus.PUBLISHED
    assert (await service.execute(youtube.id)).status == PublicationStatus.FAILED
    await session.refresh(package)
    assert package.status == PublishPackageStatus.PARTIALLY_PUBLISHED


@pytest.mark.asyncio
async def test_one_success_does_not_mark_three_variant_package_published(session, tmp_path: Path):
    package, variants, accounts = await prepared(session, tmp_path)
    registry = PublisherRegistry()
    registry.register(PublishingPlatform.TELEGRAM, FakePublisher())
    service = PublicationService(session, registry)
    publication = await service.create(
        PublicationCreate(
            platform_variant_id=variants[PublishingPlatform.TELEGRAM].id,
            platform_account_id=accounts[PublishingPlatform.TELEGRAM].id,
            publish_now=True,
        )
    )
    assert (await service.execute(publication.id)).status == PublicationStatus.PUBLISHED
    await session.refresh(package)
    assert package.status == PublishPackageStatus.PARTIALLY_PUBLISHED


@pytest.mark.asyncio
async def test_full_scheduled_multi_platform_mock_e2e(session, tmp_path: Path):
    package, variants, accounts = await prepared(session, tmp_path)
    registry = PublisherRegistry()
    telegram = FakePublisher()
    youtube = ProcessingPublisher("published")
    tiktok = ProcessingPublisher("failed")
    registry.register(PublishingPlatform.TELEGRAM, telegram)
    registry.register(PublishingPlatform.YOUTUBE, youtube)
    registry.register(PublishingPlatform.TIKTOK, tiktok)
    service = PublicationService(session, registry)
    due_at = datetime.now(UTC) + timedelta(hours=1)
    publications = []
    for platform in PublishingPlatform:
        publications.append(
            await service.create(
                PublicationCreate(
                    platform_variant_id=variants[platform].id,
                    platform_account_id=accounts[platform].id,
                    scheduled_at=due_at,
                    idempotency_key=f"e2e:{platform.value}",
                )
            )
        )
    claimed = await PublicationScheduler(session).claim_due(now=due_at + timedelta(seconds=1))
    assert set(claimed) == {item.id for item in publications}
    results = {item.platform: await service.execute(item.id) for item in publications}
    assert results[PublishingPlatform.TELEGRAM].status == PublicationStatus.PUBLISHED
    assert results[PublishingPlatform.YOUTUBE].status == PublicationStatus.PROCESSING
    assert results[PublishingPlatform.TIKTOK].status == PublicationStatus.PROCESSING
    await service.poll_status(results[PublishingPlatform.YOUTUBE].id)
    await service.poll_status(results[PublishingPlatform.TIKTOK].id)
    await session.refresh(package)
    assert (
        await service.get(results[PublishingPlatform.YOUTUBE].id)
    ).status == PublicationStatus.PUBLISHED
    assert (
        await service.get(results[PublishingPlatform.TIKTOK].id)
    ).status == PublicationStatus.FAILED
    assert package.status == PublishPackageStatus.PARTIALLY_PUBLISHED
    assert telegram.calls == youtube.calls == tiktok.calls == 1


def telegram_request(video_path: str | None = None) -> PublishRequest:
    return PublishRequest(
        publication_id=uuid.uuid4(),
        platform=PublishingPlatform.TELEGRAM,
        video_path=video_path,
        thumbnail_path=None,
        title="Title",
        caption="Caption",
        description="Description",
        hashtags=["test"],
        settings={},
        media_hash="a" * 64,
    )


def telegram_context() -> PublisherContext:
    return PublisherContext(
        account_id=uuid.uuid4(),
        external_account_id="@channel",
        username="@channel",
        settings={"chat_id": "@channel"},
        capabilities={},
    )


@pytest.mark.asyncio
async def test_telegram_publisher_preflight_and_text_remote_id():
    async def handler(request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        if method == "getMe":
            result: dict[str, Any] = {"id": 7, "username": "bot"}
        elif method == "getChatMember":
            result = {"status": "administrator", "can_post_messages": True}
        else:
            result = {"message_id": 44, "chat": {"id": -1001, "username": "channel"}}
        return httpx.Response(200, json={"ok": True, "result": result})

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://telegram.test/"
    )
    publisher = TelegramPublisher("secret", client=client)
    assert (await publisher.validate(telegram_request(), telegram_context())).ready
    result = await publisher.publish(telegram_request(), telegram_context())
    assert result.remote_id == "-1001:44"
    assert result.remote_url == "https://t.me/channel/44"
    await client.aclose()


@pytest.mark.asyncio
async def test_telegram_publisher_streams_video(tmp_path: Path):
    video = tmp_path / "short.mp4"
    video.write_bytes(b"video-bytes")
    seen = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = await request.aread()
        return httpx.Response(
            200,
            json={"ok": True, "result": {"message_id": 2, "chat": {"id": -1}}},
        )

    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://telegram.test/"
    )
    publisher = TelegramPublisher("secret", client=client)
    result = await publisher.publish(telegram_request(str(video)), telegram_context())
    assert result.remote_id == "-1:2"
    assert b"video-bytes" in seen["body"]
    await client.aclose()


@pytest.mark.asyncio
async def test_telegram_publisher_sanitizes_provider_failure():
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                403, json={"ok": False, "description": "bot is not an administrator"}
            )
        ),
        base_url="https://telegram.test/",
    )
    publisher = TelegramPublisher("secret", client=client)
    with pytest.raises(Exception) as error:
        await publisher.publish(telegram_request(), telegram_context())
    assert error.value.code == "PERMISSION_DENIED"
    assert "secret" not in str(error.value)
    await client.aclose()
