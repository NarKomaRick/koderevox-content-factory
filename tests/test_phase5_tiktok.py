import hashlib
import hmac
import json
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import func, select

from app.models import (
    PlatformAccount,
    PlatformVariant,
    Publication,
    PublishPackage,
    WebhookReceipt,
)
from app.models.enums import (
    PublicationStatus,
    PublishingPlatform,
    PublishPackageStatus,
)
from app.schemas.publishing import PublisherContext, PublishRequest
from app.services.errors import InvalidStateError
from app.services.publishers.tiktok import TikTokPublisher
from app.services.publishing_errors import InvalidMetadataError
from app.services.tiktok_webhooks import TikTokWebhookService


def tiktok_request(video: Path, **settings) -> PublishRequest:
    return PublishRequest(
        publication_id=uuid.uuid4(),
        platform=PublishingPlatform.TIKTOK,
        video_path=str(video),
        thumbnail_path=None,
        title="Двойной запрос",
        caption="Вот где спрятался баг",
        description="",
        hashtags=["код", "REST"],
        settings={
            "privacy_level": "SELF_ONLY",
            "disable_comment": False,
            "disable_duet": False,
            "disable_stitch": False,
            "user_consent_confirmed": True,
            **settings,
        },
        media_hash="a" * 64,
    )


def tiktok_context() -> PublisherContext:
    return PublisherContext(
        account_id=uuid.uuid4(),
        external_account_id="open-id",
        username="koderevox",
        settings={},
        capabilities={},
        credentials={"access_token": "token"},
    )


def creator_info(**overrides):
    return {
        "creator_username": "koderevox",
        "privacy_level_options": ["SELF_ONLY"],
        "comment_disabled": False,
        "duet_disabled": False,
        "stitch_disabled": False,
        "max_video_post_duration_sec": 300,
        **overrides,
    }


@pytest.mark.asyncio
async def test_tiktok_creator_info_private_capability_warning(tmp_path: Path):
    video = tmp_path / "short.mp4"
    video.write_bytes(b"video")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": creator_info(), "error": {"code": "ok", "message": ""}}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    publisher = TikTokPublisher(client=client)
    report = await publisher.validate(tiktok_request(video), tiktok_context())
    assert report.ready
    assert any(
        issue.code == "PRIVATE_ONLY" and issue.severity == "warning" for issue in report.issues
    )
    await client.aclose()


@pytest.mark.asyncio
async def test_tiktok_requires_explicit_consent(tmp_path: Path):
    video = tmp_path / "short.mp4"
    video.write_bytes(b"video")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"data": creator_info(), "error": {"code": "ok", "message": ""}}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    publisher = TikTokPublisher(client=client)
    report = await publisher.validate(
        tiktok_request(video, user_consent_confirmed=False), tiktok_context()
    )
    assert not report.ready
    assert any(issue.code == "CONSENT_REQUIRED" for issue in report.issues)
    await client.aclose()


@pytest.mark.asyncio
async def test_tiktok_rejects_unavailable_settings(tmp_path: Path):
    video = tmp_path / "short.mp4"
    video.write_bytes(b"video")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": creator_info(comment_disabled=True),
                "error": {"code": "ok", "message": ""},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    publisher = TikTokPublisher(client=client)
    with pytest.raises(InvalidMetadataError):
        await publisher.publish(tiktok_request(video, disable_comment=False), tiktok_context())
    await client.aclose()


@pytest.mark.asyncio
async def test_tiktok_file_upload_and_status_polling(tmp_path: Path):
    video = tmp_path / "short.mp4"
    video.write_bytes(b"video-content")
    uploaded = b""

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal uploaded
        if request.url.path.endswith("creator_info/query/"):
            return httpx.Response(
                200,
                json={"data": creator_info(), "error": {"code": "ok", "message": ""}},
            )
        if request.url.path.endswith("video/init/"):
            payload = json.loads(await request.aread())
            assert payload["source_info"]["source"] == "FILE_UPLOAD"
            return httpx.Response(
                200,
                json={
                    "data": {
                        "publish_id": "v_pub_123",
                        "upload_url": "https://upload.tiktok.test/video",
                    },
                    "error": {"code": "ok", "log_id": "request-1"},
                },
            )
        if request.url.host == "upload.tiktok.test":
            uploaded += await request.aread()
            return httpx.Response(201)
        if request.url.path.endswith("status/fetch/"):
            return httpx.Response(
                200,
                json={
                    "data": {
                        "status": "PUBLISH_COMPLETE",
                        "publicaly_available_post_id": [999],
                    },
                    "error": {"code": "ok"},
                },
            )
        return httpx.Response(404)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    publisher = TikTokPublisher(client=client)
    result = await publisher.publish(tiktok_request(video), tiktok_context())
    assert result.remote_id == "v_pub_123"
    assert result.status == "processing"
    assert uploaded == b"video-content"
    request = tiktok_request(video)
    request.remote_id = result.remote_id
    status = await publisher.get_status(request, tiktok_context())
    assert status.status == "published"
    assert status.remote_url == "https://www.tiktok.com/@koderevox/video/999"
    await client.aclose()


@pytest.mark.asyncio
async def test_tiktok_webhook_signature_and_duplicate_are_safe(session):
    project = await session.scalar(select(__import__("app.models", fromlist=["Project"]).Project))
    account = PlatformAccount(
        project_id=project.id,
        platform=PublishingPlatform.TIKTOK,
        display_name="TikTok",
        username="koderevox",
    )
    package = PublishPackage(
        project_id=project.id,
        status=PublishPackageStatus.READY,
        base_title="Title",
        base_caption="Caption",
        base_description="Description",
    )
    session.add_all([account, package])
    await session.flush()
    variant = PlatformVariant(
        publish_package_id=package.id,
        platform=PublishingPlatform.TIKTOK,
        video_path="video.mp4",
        title="Title",
        caption="Caption",
        description="",
        content_hash="a" * 64,
    )
    session.add(variant)
    await session.flush()
    publication = Publication(
        publish_package_id=package.id,
        platform_variant_id=variant.id,
        platform_account_id=account.id,
        platform=PublishingPlatform.TIKTOK,
        status=PublicationStatus.PROCESSING,
        remote_id="publish-1",
        variant_snapshot={},
        variant_hash="a" * 64,
    )
    session.add(publication)
    await session.commit()
    payload = {
        "client_key": "client-key",
        "event": "post.publish.complete",
        "create_time": int(datetime.now(UTC).timestamp()),
        "user_openid": "open-id",
        "content": json.dumps({"publish_id": "publish-1"}),
    }
    body = json.dumps(payload, separators=(",", ":")).encode()
    timestamp = int(time.time())
    signature = hmac.new(
        b"client-secret", str(timestamp).encode() + b"." + body, hashlib.sha256
    ).hexdigest()
    header = f"t={timestamp},s={signature}"
    service = TikTokWebhookService(session, "client-key", "client-secret")
    assert await service.handle(body, header) is True
    assert await service.handle(body, header) is False
    await session.refresh(publication)
    assert publication.status == PublicationStatus.PUBLISHED
    assert await session.scalar(select(func.count(WebhookReceipt.id))) == 1


@pytest.mark.asyncio
async def test_tiktok_webhook_rejects_bad_signature(session):
    service = TikTokWebhookService(session, "client-key", "client-secret")
    timestamp = int(time.time())
    with pytest.raises(InvalidStateError):
        await service.handle(b"{}", f"t={timestamp},s=bad")
