import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from cryptography.fernet import Fernet
from pydantic import ValidationError
from sqlalchemy import select

from app.core.config import Settings
from app.models import EncryptedCredential, PlatformAccount
from app.models.enums import PublishingPlatform
from app.schemas.publishing import PlatformAccountCreate, PublisherContext, PublishRequest
from app.services.credentials import EncryptedCredentialProvider, TokenManager
from app.services.errors import InvalidStateError
from app.services.oauth import OAuthService
from app.services.publishers.youtube import YouTubePublisher
from app.services.publishing_errors import (
    AuthenticationError,
    RateLimitError,
    UploadInterruptedError,
)


async def youtube_account(session) -> PlatformAccount:
    project = await session.scalar(select(__import__("app.models", fromlist=["Project"]).Project))
    account = PlatformAccount(
        project_id=project.id,
        platform=PublishingPlatform.YOUTUBE,
        display_name="Koderevox YouTube",
        capabilities={"privacy_statuses": ["private", "unlisted"]},
    )
    session.add(account)
    await session.commit()
    await session.refresh(account)
    return account


@pytest.mark.asyncio
async def test_credentials_are_authenticated_encrypted(session):
    account = await youtube_account(session)
    key = Fernet.generate_key().decode()
    provider = EncryptedCredentialProvider(session, key)
    token = "access-super-secret"
    await provider.set(account.id, {"access_token": token, "refresh_token": "refresh-secret"})
    row = await session.scalar(select(EncryptedCredential))
    assert token.encode() not in row.encrypted_payload
    assert (await provider.get(account.id))["access_token"] == token
    with pytest.raises(AuthenticationError):
        await EncryptedCredentialProvider(session, Fernet.generate_key().decode()).get(account.id)


def test_platform_account_rejects_plaintext_credentials() -> None:
    with pytest.raises(ValidationError):
        PlatformAccountCreate(
            project_id=uuid.uuid4(),
            platform=PublishingPlatform.YOUTUBE,
            display_name="unsafe",
            settings={"oauth": {"refresh_token": "must-not-be-here"}},
        )


@pytest.mark.asyncio
async def test_youtube_token_refresh_is_transparent_and_persisted(session):
    account = await youtube_account(session)
    provider = EncryptedCredentialProvider(session, Fernet.generate_key().decode())
    await provider.set(
        account.id,
        {
            "access_token": "expired",
            "refresh_token": "keep-me",
            "expires_at": (datetime.now(UTC) - timedelta(minutes=1)).isoformat(),
        },
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert b"refresh_token=keep-me" in await request.aread()
        return httpx.Response(200, json={"access_token": "fresh", "expires_in": 3600})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    manager = TokenManager(
        session,
        provider,
        Settings(youtube_client_id="client", youtube_client_secret="secret"),
        client=client,
    )
    credentials = await manager.get(account.id)
    assert credentials["access_token"] == "fresh"
    assert credentials["refresh_token"] == "keep-me"
    assert (await provider.get(account.id))["access_token"] == "fresh"
    await client.aclose()


class FakeTokenManager:
    def __init__(self) -> None:
        self.calls = 0

    async def exchange_code(self, account, code, *, code_verifier=None):
        self.calls += 1
        return {"access_token": "stored"}


@pytest.mark.asyncio
async def test_oauth_state_is_single_use_and_csrf_checked(session):
    account = await youtube_account(session)
    settings = Settings(
        youtube_client_id="client",
        youtube_client_secret="secret",
        youtube_redirect_uri="https://example.test/oauth/youtube/callback",
    )
    tokens = FakeTokenManager()
    service = OAuthService(session, settings, tokens)  # type: ignore[arg-type]
    started = await service.start(account.id)
    state = started.authorization_url.split("state=", 1)[1].split("&", 1)[0]
    await service.callback(PublishingPlatform.YOUTUBE, state, "code")
    with pytest.raises(InvalidStateError):
        await service.callback(PublishingPlatform.YOUTUBE, state, "code")
    with pytest.raises(InvalidStateError):
        await service.callback(PublishingPlatform.YOUTUBE, "forged", "code")
    assert tokens.calls == 1


def youtube_request(video: Path, thumbnail: Path | None = None) -> PublishRequest:
    return PublishRequest(
        publication_id=uuid.uuid4(),
        platform=PublishingPlatform.YOUTUBE,
        video_path=str(video),
        thumbnail_path=str(thumbnail) if thumbnail else None,
        title="Why the request was sent twice",
        caption="",
        description="Technical details",
        hashtags=["REST"],
        settings={"privacy_status": "private", "made_for_kids": False},
        media_hash="a" * 64,
    )


def youtube_context() -> PublisherContext:
    return PublisherContext(
        account_id=uuid.uuid4(),
        external_account_id=None,
        username=None,
        settings={},
        capabilities={"privacy_statuses": ["private"]},
        credentials={"access_token": "oauth-token"},
    )


@pytest.mark.asyncio
async def test_youtube_resumable_upload_and_processing_status(tmp_path: Path):
    video = tmp_path / "short.mp4"
    video.write_bytes(b"youtube-video")
    calls: list[tuple[str, str]] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path.endswith("/videos"):
            return httpx.Response(200, headers={"Location": "https://upload.test/session"})
        if request.url.host == "upload.test" and request.headers.get(
            "Content-Range", ""
        ).startswith("bytes */"):
            return httpx.Response(308)
        if request.url.host == "upload.test":
            assert b"youtube-video" == await request.aread()
            return httpx.Response(200, json={"id": "video-123"})
        if request.method == "GET" and request.url.path.endswith("/videos"):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "status": {"uploadStatus": "processed"},
                            "processingDetails": {"processingStatus": "succeeded"},
                        }
                    ]
                },
            )
        return httpx.Response(200, json={"items": [{"id": "channel"}]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    publisher = YouTubePublisher(client=client, chunk_size=256 * 1024)
    request = youtube_request(video)
    assert (await publisher.validate(request, youtube_context())).ready
    result = await publisher.publish(request, youtube_context())
    assert result.remote_id == "video-123"
    assert result.status == "processing"
    request.remote_id = result.remote_id
    status = await publisher.get_status(request, youtube_context())
    assert status.status == "published"
    assert sum(path.endswith("/videos") for method, path in calls if method == "POST") == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_youtube_thumbnail_failure_does_not_upload_video_twice(tmp_path: Path):
    video = tmp_path / "short.mp4"
    thumbnail = tmp_path / "cover.jpg"
    video.write_bytes(b"video")
    thumbnail.write_bytes(b"jpeg")
    init_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal init_calls
        if request.method == "POST" and request.url.path.endswith("/videos"):
            init_calls += 1
            return httpx.Response(200, headers={"Location": "https://upload.test/session"})
        if request.url.host == "upload.test" and "bytes */" in request.headers.get(
            "Content-Range", ""
        ):
            return httpx.Response(308)
        if request.url.host == "upload.test":
            return httpx.Response(200, json={"id": "video-1"})
        if request.url.path.endswith("/thumbnails/set"):
            return httpx.Response(
                400,
                json={"error": {"errors": [{"reason": "invalidImage"}]}},
            )
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    publisher = YouTubePublisher(client=client)
    result = await publisher.publish(youtube_request(video, thumbnail), youtube_context())
    assert result.remote_id == "video-1"
    assert result.warning is not None
    assert init_calls == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_youtube_resume_session_is_encrypted_and_reused(tmp_path: Path):
    video = tmp_path / "short.mp4"
    video.write_bytes(b"resumable-video")
    init_calls = 0
    upload_calls = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal init_calls, upload_calls
        if request.method == "POST" and request.url.path.endswith("/videos"):
            init_calls += 1
            return httpx.Response(200, headers={"Location": "https://upload.test/secret-session"})
        if request.url.host == "upload.test" and "bytes */" in request.headers.get(
            "Content-Range", ""
        ):
            return httpx.Response(308)
        if request.url.host == "upload.test":
            upload_calls += 1
            if upload_calls == 1:
                raise httpx.ConnectError("interrupted", request=request)
            return httpx.Response(200, json={"id": "video-resumed"})
        return httpx.Response(500)

    key = Fernet.generate_key().decode()
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    publisher = YouTubePublisher(client=client, encryption_key=key)
    request = youtube_request(video)
    with pytest.raises(UploadInterruptedError) as caught:
        await publisher.publish(request, youtube_context())
    encrypted = str(caught.value.provider_metadata["youtube_upload_session"])
    assert "secret-session" not in encrypted
    result = await publisher.publish(
        request.model_copy(update={"provider_metadata": caught.value.provider_metadata}),
        youtube_context(),
    )
    assert result.remote_id == "video-resumed"
    assert init_calls == 1
    await client.aclose()


@pytest.mark.asyncio
async def test_youtube_rate_limit_is_retryable(tmp_path: Path):
    video = tmp_path / "short.mp4"
    video.write_bytes(b"video")
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                403,
                json={"error": {"errors": [{"reason": "quotaExceeded"}]}},
            )
        )
    )
    publisher = YouTubePublisher(client=client)
    with pytest.raises(RateLimitError):
        await publisher.publish(youtube_request(video), youtube_context())
    await client.aclose()


@pytest.mark.asyncio
async def test_youtube_auth_failure_is_not_retryable(tmp_path: Path):
    video = tmp_path / "short.mp4"
    video.write_bytes(b"video")
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(401, json={})),
    )
    publisher = YouTubePublisher(client=client)
    with pytest.raises(AuthenticationError):
        await publisher.publish(youtube_request(video), youtube_context())
    await client.aclose()
