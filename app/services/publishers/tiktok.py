import asyncio
import math
from pathlib import Path
from typing import Any

import aiofiles
import httpx

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
    RateLimitError,
)


class TikTokPublisher:
    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        api_base_url: str = "https://open.tiktokapis.com",
        chunk_size: int = 10_000_000,
    ) -> None:
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=120)
        self.api_base_url = api_base_url.rstrip("/")
        self.chunk_size = min(max(chunk_size, 5_000_000), 64_000_000)

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def creator_info(self, context: PublisherContext) -> dict[str, Any]:
        body = await self._post_json("/v2/post/publish/creator_info/query/", {}, context)
        return dict(body.get("data", {}))

    async def validate(
        self, request: PublishRequest, context: PublisherContext
    ) -> PlatformValidationResult:
        issues: list[ValidationIssue] = []
        if not context.credentials.get("access_token"):
            issues.append(
                ValidationIssue(code="AUTH_REQUIRED", message="TikTok OAuth не подключён.")
            )
            return PlatformValidationResult(
                platform=PublishingPlatform.TIKTOK, ready=False, issues=issues
            )
        path = Path(request.video_path or "")
        if not request.video_path or not await asyncio.to_thread(path.is_file):
            issues.append(ValidationIssue(code="INVALID_MEDIA", message="Видео не найдено."))
        if not request.settings.get("user_consent_confirmed", False):
            issues.append(
                ValidationIssue(
                    code="CONSENT_REQUIRED",
                    message="Подтвердите TikTok visibility/comment/duet/stitch settings.",
                )
            )
        capabilities = await self.creator_info(context)
        privacy = request.settings.get("privacy_level")
        options = capabilities.get("privacy_level_options", [])
        if privacy not in options:
            issues.append(
                ValidationIssue(
                    code="INVALID_METADATA",
                    message=f"TikTok visibility {privacy} недоступна этому аккаунту.",
                )
            )
        for setting, disabled_capability, label in (
            ("disable_comment", "comment_disabled", "comments"),
            ("disable_duet", "duet_disabled", "duet"),
            ("disable_stitch", "stitch_disabled", "stitch"),
        ):
            if capabilities.get(disabled_capability) and not request.settings.get(setting, False):
                issues.append(
                    ValidationIssue(
                        code="INVALID_METADATA",
                        message=f"TikTok account does not allow {label}.",
                    )
                )
        duration = request.settings.get("duration_seconds")
        maximum = capabilities.get("max_video_post_duration_sec")
        if duration and maximum and float(duration) > float(maximum):
            issues.append(
                ValidationIssue(code="INVALID_MEDIA", message="Видео длиннее лимита аккаунта.")
            )
        if options == ["SELF_ONLY"]:
            issues.append(
                ValidationIssue(
                    code="PRIVATE_ONLY",
                    message="Интеграция позволяет только приватную публикацию.",
                    severity="warning",
                )
            )
        return PlatformValidationResult(
            platform=PublishingPlatform.TIKTOK,
            ready=not any(issue.severity == "error" for issue in issues),
            issues=issues,
            capabilities=capabilities,
        )

    async def publish(self, request: PublishRequest, context: PublisherContext) -> PublishResult:
        path = Path(request.video_path or "")
        if not await asyncio.to_thread(path.is_file):
            raise InvalidMediaError()
        capabilities = await self.creator_info(context)
        self._validate_settings(request, capabilities)
        size = (await asyncio.to_thread(path.stat)).st_size
        existing_publish_id = request.provider_metadata.get("publish_id")
        if existing_publish_id:
            status = await self.get_status(
                request.model_copy(update={"remote_id": str(existing_publish_id)}), context
            )
            if status.status in {"processing", "published"}:
                return PublishResult(
                    remote_id=str(existing_publish_id),
                    remote_url=status.remote_url,
                    status="processing" if status.status == "processing" else "published",
                    provider_metadata={
                        "publish_id": str(existing_publish_id),
                        **status.provider_metadata,
                    },
                )
            raise ProviderPermanentError(
                "Existing TikTok upload cannot be restarted safely",
                provider_code="AMBIGUOUS_PROVIDER_STATE",
            )
        chunk_size, count = self._chunk_plan(size)
        init = await self._post_json(
            "/v2/post/publish/video/init/",
            {
                "post_info": {
                    "title": self._caption(request),
                    "privacy_level": request.settings["privacy_level"],
                    "disable_duet": bool(request.settings.get("disable_duet", False)),
                    "disable_comment": bool(request.settings.get("disable_comment", False)),
                    "disable_stitch": bool(request.settings.get("disable_stitch", False)),
                    "video_cover_timestamp_ms": int(
                        request.settings.get("video_cover_timestamp_ms", 1000)
                    ),
                },
                "source_info": {
                    "source": "FILE_UPLOAD",
                    "video_size": size,
                    "chunk_size": chunk_size,
                    "total_chunk_count": count,
                },
            },
            context,
        )
        data = init.get("data", {})
        publish_id = str(data.get("publish_id", ""))
        upload_url = str(data.get("upload_url", ""))
        if not publish_id or not upload_url:
            raise ProviderTemporaryError("TikTok init response is incomplete")
        try:
            await self._upload(upload_url, path, size, chunk_size, count)
        except ProviderTemporaryError as exc:
            raise ProviderTemporaryError(
                provider_code=exc.provider_code,
                provider_metadata={"publish_id": publish_id},
            ) from exc
        return PublishResult(
            remote_id=publish_id,
            status="processing",
            provider_request_id=str(init.get("error", {}).get("log_id") or "") or None,
            provider_metadata={
                "publish_id": publish_id,
                "creator_info": capabilities,
                "visibility": request.settings["privacy_level"],
            },
        )

    async def get_status(
        self, request: PublishRequest, context: PublisherContext
    ) -> ProviderStatusResult:
        publish_id = request.remote_id or request.provider_metadata.get("publish_id")
        if not publish_id:
            return ProviderStatusResult(status="failed", error_code="REMOTE_ID_MISSING")
        body = await self._post_json(
            "/v2/post/publish/status/fetch/", {"publish_id": publish_id}, context
        )
        data = dict(body.get("data", {}))
        status = data.get("status")
        if status == "PUBLISH_COMPLETE":
            post_ids = data.get("publicaly_available_post_id", [])
            username = str(context.username or "").lstrip("@")
            remote_url = (
                f"https://www.tiktok.com/@{username}/video/{post_ids[0]}"
                if username and post_ids
                else None
            )
            return ProviderStatusResult(
                status="published",
                remote_id=str(publish_id),
                remote_url=remote_url,
                provider_metadata=data,
            )
        if status == "FAILED":
            reason = str(data.get("fail_reason", "unknown"))
            return ProviderStatusResult(
                status="failed",
                remote_id=str(publish_id),
                error_code=reason,
                error_message="TikTok processing failed.",
                provider_metadata=data,
            )
        return ProviderStatusResult(
            status="processing", remote_id=str(publish_id), provider_metadata=data
        )

    async def delete(self, request: PublishRequest, context: PublisherContext) -> None:
        return None

    def _validate_settings(self, request: PublishRequest, capabilities: dict[str, Any]) -> None:
        if not request.settings.get("user_consent_confirmed"):
            raise InvalidMetadataError("TikTok user consent is required")
        if request.settings.get("privacy_level") not in capabilities.get(
            "privacy_level_options", []
        ):
            raise InvalidMetadataError("TikTok privacy option is unavailable")
        for setting, capability in (
            ("disable_comment", "comment_disabled"),
            ("disable_duet", "duet_disabled"),
            ("disable_stitch", "stitch_disabled"),
        ):
            if capabilities.get(capability) and not request.settings.get(setting, False):
                raise InvalidMetadataError(f"TikTok setting {setting} is unavailable")

    async def _upload(
        self,
        upload_url: str,
        path: Path,
        size: int,
        chunk_size: int,
        count: int,
    ) -> None:
        offset = 0
        async with aiofiles.open(path, "rb") as handle:
            for index in range(count):
                length = chunk_size if index < count - 1 else size - offset
                chunk = await handle.read(length)
                end = offset + len(chunk) - 1
                try:
                    response = await self.client.put(
                        upload_url,
                        headers={
                            "Content-Type": "video/mp4",
                            "Content-Length": str(len(chunk)),
                            "Content-Range": f"bytes {offset}-{end}/{size}",
                        },
                        content=chunk,
                    )
                except (httpx.TimeoutException, httpx.NetworkError) as exc:
                    raise ProviderTemporaryError("TikTok upload interrupted") from exc
                expected = 201 if index == count - 1 else 206
                if response.status_code != expected:
                    self._raise(response)
                    raise ProviderTemporaryError("TikTok returned unexpected upload status")
                offset = end + 1

    def _chunk_plan(self, size: int) -> tuple[int, int]:
        if size <= 0:
            raise InvalidMediaError("Video file is empty")
        if size < 5_000_000:
            return size, 1
        if size <= 64_000_000:
            return size, 1
        count = math.floor(size / self.chunk_size)
        if count > 1000:
            raise InvalidMediaError("Video requires too many TikTok chunks")
        return self.chunk_size, count

    async def _post_json(
        self, path: str, payload: dict[str, Any], context: PublisherContext
    ) -> dict[str, Any]:
        token = context.credentials.get("access_token")
        if not token:
            raise AuthenticationError()
        try:
            response = await self.client.post(
                f"{self.api_base_url}{path}",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json; charset=UTF-8",
                },
                json=payload,
            )
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderTemporaryError() from exc
        self._raise(response)
        try:
            body = dict(response.json())
        except ValueError as exc:
            raise ProviderTemporaryError("TikTok returned invalid JSON") from exc
        error = body.get("error", {})
        if error and error.get("code") not in {None, "ok"}:
            self._raise_code(str(error.get("code")))
        return body

    @staticmethod
    def _caption(request: PublishRequest) -> str:
        tags = " ".join(f"#{tag.lstrip('#')}" for tag in request.hashtags)
        return " ".join(item for item in (request.caption or request.title, tags) if item)[:2200]

    @classmethod
    def _raise(cls, response: httpx.Response) -> None:
        if response.is_success:
            return
        if response.status_code == 401:
            raise AuthenticationError(provider_code="access_token_invalid")
        if response.status_code == 429:
            raise RateLimitError(provider_code="rate_limit_exceeded")
        if response.status_code >= 500:
            raise ProviderTemporaryError(provider_code="internal_error")
        if response.status_code in {403, 404}:
            raise ProviderPermanentError(provider_code=str(response.status_code))
        try:
            code = str(response.json().get("error", {}).get("code", response.status_code))
        except (ValueError, TypeError, AttributeError):
            code = str(response.status_code)
        cls._raise_code(code)

    @staticmethod
    def _raise_code(code: str) -> None:
        if code in {"access_token_invalid", "scope_not_authorized"}:
            raise AuthenticationError(provider_code=code)
        if code == "rate_limit_exceeded":
            raise RateLimitError(provider_code=code)
        if code in {"internal_error", "video_pull_failed"}:
            raise ProviderTemporaryError(provider_code=code)
        if code in {
            "privacy_level_option_mismatch",
            "invalid_params",
            "invalid_publish_id",
        }:
            raise InvalidMetadataError(provider_code=code)
        if code.startswith("spam_risk") or code in {
            "unaudited_client_can_only_post_to_private_accounts"
        }:
            raise PolicyRejectedError(provider_code=code)
        raise ProviderPermanentError(provider_code=code)
