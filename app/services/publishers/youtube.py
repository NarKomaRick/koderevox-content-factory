import asyncio
import json
from pathlib import Path
from typing import Any

import aiofiles
import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.models.enums import PublishingPlatform
from app.schemas.publishing import (
    PlatformValidationResult,
    ProviderStatusResult,
    PublisherContext,
    PublishRequest,
    PublishResult,
    ValidationIssue,
)
from app.services.publishing_errors import (
    AuthenticationError,
    InvalidMediaError,
    InvalidMetadataError,
    PolicyRejectedError,
    ProviderPermanentError,
    ProviderTemporaryError,
    PublisherPermissionError,
    RateLimitError,
    UploadInterruptedError,
)


class YouTubePublisher:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        api_base_url: str = "https://www.googleapis.com/youtube/v3",
        upload_base_url: str = "https://www.googleapis.com/upload/youtube/v3",
        chunk_size: int = 8 * 1024 * 1024,
        encryption_key: str = "",
    ) -> None:
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=120)
        self.api_base_url = api_base_url.rstrip("/")
        self.upload_base_url = upload_base_url.rstrip("/")
        self.chunk_size = max(256 * 1024, chunk_size // (256 * 1024) * (256 * 1024))
        self._fernet = Fernet(encryption_key.encode()) if encryption_key else None

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def validate(
        self, request: PublishRequest, context: PublisherContext
    ) -> PlatformValidationResult:
        issues: list[ValidationIssue] = []
        if not context.credentials.get("access_token"):
            issues.append(
                ValidationIssue(code="AUTH_REQUIRED", message="YouTube OAuth не подключён.")
            )
        path = Path(request.video_path or "")
        if not request.video_path or not await asyncio.to_thread(path.is_file):
            issues.append(ValidationIssue(code="INVALID_MEDIA", message="Видео не найдено."))
        if not request.title or len(request.title) > 100:
            issues.append(
                ValidationIssue(code="INVALID_METADATA", message="YouTube title должен быть 1–100.")
            )
        if len(request.description) > 5000:
            issues.append(
                ValidationIssue(code="INVALID_METADATA", message="Описание длиннее 5000 знаков.")
            )
        privacy = request.settings.get("privacy_status", "private")
        allowed = set(context.capabilities.get("privacy_statuses", ["private"]))
        if privacy not in allowed:
            issues.append(
                ValidationIssue(
                    code="INVALID_METADATA",
                    message=f"Visibility {privacy} недоступна для аккаунта.",
                )
            )
        if not issues:
            await self._json_request(
                "GET",
                f"{self.api_base_url}/channels",
                context,
                params={"part": "id", "mine": "true"},
            )
        return PlatformValidationResult(
            platform=PublishingPlatform.YOUTUBE,
            ready=not issues,
            issues=issues,
            capabilities=context.capabilities,
        )

    async def publish(self, request: PublishRequest, context: PublisherContext) -> PublishResult:
        video_id = request.remote_id
        encrypted_session = request.provider_metadata.get("youtube_upload_session")
        upload_url = (
            self._decrypt_upload_session(str(encrypted_session)) if encrypted_session else None
        )
        if video_id is None:
            if not upload_url:
                upload_url = await self._start_upload(request, context)
            try:
                video_id = await self._upload_chunks(
                    str(upload_url), Path(request.video_path or ""), context
                )
            except ProviderTemporaryError as exc:
                if self._fernet is None:
                    raise ProviderPermanentError(
                        "Upload state cannot be persisted securely",
                        provider_code="SECURE_RESUME_STATE_UNAVAILABLE",
                    ) from exc
                raise UploadInterruptedError(
                    provider_code=exc.provider_code,
                    provider_metadata={
                        "youtube_upload_session": self._fernet.encrypt(
                            str(upload_url).encode()
                        ).decode()
                    },
                ) from exc
        warning = None
        if request.thumbnail_path:
            try:
                await self._set_thumbnail(video_id, Path(request.thumbnail_path), context)
            except (InvalidMediaError, InvalidMetadataError, ProviderTemporaryError) as exc:
                warning = f"Видео загружено, но обложка не установлена: {exc.user_message}"
        return PublishResult(
            remote_id=video_id,
            remote_url=f"https://youtu.be/{video_id}",
            status="processing",
            provider_metadata={"video_id": video_id, "upload_complete": True},
            warning=warning,
        )

    async def get_status(
        self, request: PublishRequest, context: PublisherContext
    ) -> ProviderStatusResult:
        if not request.remote_id:
            return ProviderStatusResult(status="failed", error_code="REMOTE_ID_MISSING")
        body = await self._json_request(
            "GET",
            f"{self.api_base_url}/videos",
            context,
            params={"part": "status,processingDetails", "id": request.remote_id},
        )
        items = body.get("items", [])
        if not items:
            return ProviderStatusResult(status="failed", error_code="REMOTE_NOT_FOUND")
        item = items[0]
        upload_status = item.get("status", {}).get("uploadStatus")
        processing = item.get("processingDetails", {}).get("processingStatus")
        if upload_status in {"rejected", "deleted", "failed"} or processing == "failed":
            return ProviderStatusResult(
                status="failed",
                remote_id=request.remote_id,
                error_code="PROCESSING_FAILED",
                provider_metadata=item,
            )
        if upload_status == "processed" or processing == "succeeded":
            return ProviderStatusResult(
                status="published",
                remote_id=request.remote_id,
                remote_url=f"https://youtu.be/{request.remote_id}",
                provider_metadata=item,
            )
        return ProviderStatusResult(
            status="processing", remote_id=request.remote_id, provider_metadata=item
        )

    async def delete(self, request: PublishRequest, context: PublisherContext) -> None:
        if request.remote_id:
            await self._json_request(
                "DELETE",
                f"{self.api_base_url}/videos",
                context,
                params={"id": request.remote_id},
            )

    async def _start_upload(self, request: PublishRequest, context: PublisherContext) -> str:
        path = Path(request.video_path or "")
        if not await asyncio.to_thread(path.is_file):
            raise InvalidMediaError()
        size = (await asyncio.to_thread(path.stat)).st_size
        tags = list(request.settings.get("tags", [])) or request.hashtags
        body = {
            "snippet": {
                "title": request.title,
                "description": request.description,
                "tags": tags,
                "categoryId": str(request.settings.get("category_id", "28")),
            },
            "status": {
                "privacyStatus": request.settings.get("privacy_status", "private"),
                "selfDeclaredMadeForKids": bool(request.settings.get("made_for_kids", False)),
            },
        }
        headers = self._headers(context)
        headers.update(
            {
                "Content-Type": "application/json; charset=UTF-8",
                "X-Upload-Content-Length": str(size),
                "X-Upload-Content-Type": "video/mp4",
            }
        )
        try:
            response = await self.client.post(
                f"{self.upload_base_url}/videos",
                params={"uploadType": "resumable", "part": "snippet,status"},
                headers=headers,
                content=json.dumps(body).encode(),
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderTemporaryError() from exc
        self._raise(response)
        location = response.headers.get("Location")
        if not location:
            raise ProviderTemporaryError("YouTube omitted resumable upload URL")
        return location

    async def _upload_chunks(self, upload_url: str, path: Path, context: PublisherContext) -> str:
        if not await asyncio.to_thread(path.is_file):
            raise InvalidMediaError()
        total = (await asyncio.to_thread(path.stat)).st_size
        offset, completed_id = await self._resume_offset(upload_url, total, context)
        if completed_id:
            return completed_id
        async with aiofiles.open(path, "rb") as handle:
            await handle.seek(offset)
            while offset < total:
                chunk = await handle.read(min(self.chunk_size, total - offset))
                end = offset + len(chunk) - 1
                headers = self._headers(context)
                headers.update(
                    {
                        "Content-Type": "video/mp4",
                        "Content-Length": str(len(chunk)),
                        "Content-Range": f"bytes {offset}-{end}/{total}",
                    }
                )
                try:
                    response = await self.client.put(upload_url, headers=headers, content=chunk)
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    raise ProviderTemporaryError() from exc
                if response.status_code == 308:
                    offset = self._range_offset(response.headers.get("Range"), end + 1)
                    await handle.seek(offset)
                    continue
                self._raise(response)
                try:
                    return str(response.json()["id"])
                except (ValueError, KeyError, TypeError) as exc:
                    raise ProviderTemporaryError("YouTube upload response has no video ID") from exc
        raise ProviderTemporaryError("YouTube upload ended without a video ID")

    async def _resume_offset(
        self, upload_url: str, total: int, context: PublisherContext
    ) -> tuple[int, str | None]:
        headers = self._headers(context)
        headers.update({"Content-Length": "0", "Content-Range": f"bytes */{total}"})
        try:
            response = await self.client.put(upload_url, headers=headers, content=b"")
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderTemporaryError() from exc
        if response.status_code == 308:
            return self._range_offset(response.headers.get("Range"), 0), None
        if response.is_success:
            try:
                completed_id = response.json().get("id")
                return (total, str(completed_id)) if completed_id else (0, None)
            except ValueError:
                return 0, None
        if response.status_code == 404:
            return 0, None
        self._raise(response)
        return 0, None

    async def _set_thumbnail(self, video_id: str, path: Path, context: PublisherContext) -> None:
        if not await asyncio.to_thread(path.is_file):
            raise InvalidMediaError("Thumbnail file does not exist")
        async with aiofiles.open(path, "rb") as handle:
            content = await handle.read()
        try:
            response = await self.client.post(
                "https://www.googleapis.com/upload/youtube/v3/thumbnails/set",
                params={"videoId": video_id, "uploadType": "media"},
                headers={**self._headers(context), "Content-Type": "image/jpeg"},
                content=content,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderTemporaryError() from exc
        self._raise(response)

    def _decrypt_upload_session(self, encrypted: str) -> str:
        if self._fernet is None:
            raise ProviderPermanentError(
                "Secure upload state cannot be decrypted",
                provider_code="SECURE_RESUME_STATE_UNAVAILABLE",
            )
        try:
            return self._fernet.decrypt(encrypted.encode()).decode()
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise ProviderPermanentError(
                "Secure upload state is invalid", provider_code="INVALID_RESUME_STATE"
            ) from exc

    async def _json_request(
        self,
        method: str,
        url: str,
        context: PublisherContext,
        **kwargs: Any,
    ) -> dict[str, Any]:
        try:
            response = await self.client.request(
                method, url, headers=self._headers(context), **kwargs
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderTemporaryError() from exc
        self._raise(response)
        if response.status_code == 204:
            return {}
        try:
            return dict(response.json())
        except ValueError as exc:
            raise ProviderTemporaryError("YouTube returned invalid JSON") from exc

    @staticmethod
    def _headers(context: PublisherContext) -> dict[str, str]:
        token = context.credentials.get("access_token")
        if not token:
            raise AuthenticationError()
        return {"Authorization": f"Bearer {token}"}

    @staticmethod
    def _range_offset(value: str | None, fallback: int) -> int:
        if not value or "-" not in value:
            return fallback
        try:
            return int(value.rsplit("-", 1)[1]) + 1
        except ValueError:
            return fallback

    @staticmethod
    def _raise(response: httpx.Response) -> None:
        if response.is_success or response.status_code == 308:
            return
        reason = ""
        try:
            errors = response.json().get("error", {}).get("errors", [])
            reason = str(errors[0].get("reason", "")) if errors else ""
        except (ValueError, TypeError, AttributeError):
            pass
        if response.status_code == 401:
            raise AuthenticationError(provider_code=reason)
        if response.status_code == 429 or reason in {
            "quotaExceeded",
            "rateLimitExceeded",
            "userRateLimitExceeded",
        }:
            raise RateLimitError(provider_code=reason)
        if response.status_code == 403:
            if reason in {"forbidden", "insufficientPermissions", "youtubeSignupRequired"}:
                raise PublisherPermissionError(provider_code=reason)
            raise PolicyRejectedError(provider_code=reason)
        if response.status_code >= 500:
            raise ProviderTemporaryError(provider_code=reason)
        if response.status_code == 400:
            raise InvalidMetadataError(provider_code=reason)
        raise ProviderPermanentError(provider_code=reason)
