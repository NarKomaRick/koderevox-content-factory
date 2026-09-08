import asyncio
from pathlib import Path
from typing import Any

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
from app.services.platform_profiles import PlatformMediaProfiles
from app.services.publishing_errors import (
    AuthenticationError,
    InvalidMediaError,
    InvalidMetadataError,
    ProviderTemporaryError,
    PublisherPermissionError,
    RateLimitError,
)


class TelegramPublisher:
    def __init__(
        self,
        bot_token: str,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str | None = None,
    ) -> None:
        self._configured = bool(bot_token)
        self._owns_client = client is None
        endpoint = base_url or f"https://api.telegram.org/bot{bot_token}"
        self.client = client or httpx.AsyncClient(base_url=endpoint, timeout=120)
        self.profile = PlatformMediaProfiles().get(PublishingPlatform.TELEGRAM)

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def validate(
        self, request: PublishRequest, context: PublisherContext
    ) -> PlatformValidationResult:
        issues: list[ValidationIssue] = []
        chat_id = context.settings.get("chat_id") or context.external_account_id or context.username
        if not self._configured:
            issues.append(ValidationIssue(code="AUTH_REQUIRED", message="Bot token не настроен."))
        if not chat_id:
            issues.append(
                ValidationIssue(code="ACCOUNT_NOT_CONFIGURED", message="Не задан Telegram channel.")
            )
        if request.video_path:
            path = Path(request.video_path)
            if not await asyncio.to_thread(path.is_file):
                issues.append(ValidationIssue(code="INVALID_MEDIA", message="Видео не найдено."))
            elif (
                self.profile.max_file_size_bytes
                and (await asyncio.to_thread(path.stat)).st_size > self.profile.max_file_size_bytes
            ):
                issues.append(
                    ValidationIssue(code="INVALID_MEDIA", message="Видео превышает лимит Bot API.")
                )
        elif request.thumbnail_path and not await asyncio.to_thread(
            Path(request.thumbnail_path).is_file
        ):
            issues.append(ValidationIssue(code="INVALID_MEDIA", message="Изображение не найдено."))
        if request.video_path or request.thumbnail_path:
            if len(self._caption(request)) > self.profile.max_caption_length:
                issues.append(
                    ValidationIssue(code="INVALID_METADATA", message="Caption длиннее 1024 знаков.")
                )
        elif len(self._text(request)) > self.profile.max_description_length:
            issues.append(
                ValidationIssue(
                    code="INVALID_METADATA", message="Telegram post длиннее 4096 знаков."
                )
            )
        if not issues and chat_id:
            try:
                me = await self._call("getMe", {})
                member = await self._call(
                    "getChatMember", {"chat_id": str(chat_id), "user_id": me["id"]}
                )
                if member.get("status") not in {"administrator", "creator"}:
                    issues.append(
                        ValidationIssue(
                            code="PERMISSION_DENIED",
                            message="Бот не является администратором канала.",
                        )
                    )
                elif member.get("status") == "administrator" and not member.get(
                    "can_post_messages", False
                ):
                    issues.append(
                        ValidationIssue(
                            code="PERMISSION_DENIED",
                            message="У бота нет права публиковать сообщения.",
                        )
                    )
            except (AuthenticationError, PublisherPermissionError, ProviderTemporaryError) as exc:
                issues.append(ValidationIssue(code=exc.code, message=exc.user_message))
        return PlatformValidationResult(
            platform=PublishingPlatform.TELEGRAM,
            ready=not any(issue.severity == "error" for issue in issues),
            issues=issues,
            capabilities={"text": True, "video": True, "photo": True},
        )

    async def publish(self, request: PublishRequest, context: PublisherContext) -> PublishResult:
        chat_id = context.settings.get("chat_id") or context.external_account_id or context.username
        if not chat_id:
            raise InvalidMetadataError("Telegram channel is not configured")
        payload: dict[str, Any] = {"chat_id": str(chat_id)}
        files: dict[str, Any] = {}
        handles: list[Any] = []
        try:
            if request.video_path:
                path = Path(request.video_path)
                if not await asyncio.to_thread(path.is_file):
                    raise InvalidMediaError("Video file does not exist")
                payload["caption"] = self._caption(request)
                handle = await asyncio.to_thread(path.open, "rb")
                handles.append(handle)
                files["video"] = (path.name, handle, "video/mp4")
                thumbnail = Path(request.thumbnail_path) if request.thumbnail_path else None
                if thumbnail is not None:
                    thumbnail_exists = await asyncio.to_thread(thumbnail.is_file)
                    if (
                        thumbnail_exists
                        and (await asyncio.to_thread(thumbnail.stat)).st_size <= 200_000
                    ):
                        thumb_handle = await asyncio.to_thread(thumbnail.open, "rb")
                        handles.append(thumb_handle)
                        files["thumbnail"] = (thumbnail.name, thumb_handle, "image/jpeg")
                result = await self._call("sendVideo", payload, files=files)
            elif request.thumbnail_path:
                path = Path(request.thumbnail_path)
                if not await asyncio.to_thread(path.is_file):
                    raise InvalidMediaError("Photo file does not exist")
                payload["caption"] = self._caption(request)
                handle = await asyncio.to_thread(path.open, "rb")
                handles.append(handle)
                result = await self._call(
                    "sendPhoto", payload, files={"photo": (path.name, handle, "image/jpeg")}
                )
            else:
                payload["text"] = self._text(request)
                result = await self._call("sendMessage", payload)
        finally:
            for handle in handles:
                handle.close()
        message_id = str(result["message_id"])
        result_chat = result.get("chat", {})
        remote_chat_id = str(result_chat.get("id", chat_id))
        username = result_chat.get("username") or str(context.username or "").lstrip("@")
        remote_url = f"https://t.me/{username}/{message_id}" if username else None
        return PublishResult(
            remote_id=f"{remote_chat_id}:{message_id}",
            remote_url=remote_url,
            provider_metadata={"chat_id": remote_chat_id, "message_id": int(message_id)},
        )

    async def get_status(
        self, request: PublishRequest, context: PublisherContext
    ) -> ProviderStatusResult:
        return ProviderStatusResult(
            status="published" if request.remote_id else "failed", remote_id=request.remote_id
        )

    async def delete(self, request: PublishRequest, context: PublisherContext) -> None:
        if not request.remote_id:
            return
        chat_id, message_id = request.remote_id.rsplit(":", 1)
        await self._call("deleteMessage", {"chat_id": chat_id, "message_id": message_id})

    async def _call(
        self, method: str, data: dict[str, Any], *, files: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if not self._configured:
            raise AuthenticationError("Telegram bot token is not configured")
        try:
            response = await self.client.post(method, data=data, files=files)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderTemporaryError("Telegram network failure") from exc
        if response.status_code == 429:
            raise RateLimitError("Telegram rate limit", provider_code="429")
        try:
            body = response.json()
        except ValueError as exc:
            raise ProviderTemporaryError("Telegram returned invalid JSON") from exc
        if response.is_success and body.get("ok"):
            return dict(body["result"])
        description = str(body.get("description", ""))
        error_code = str(body.get("error_code", response.status_code))
        lowered = description.lower()
        if response.status_code == 401:
            raise AuthenticationError(provider_code=error_code)
        if response.status_code == 403 or "not enough rights" in lowered:
            raise PublisherPermissionError(provider_code=error_code)
        if response.status_code >= 500:
            raise ProviderTemporaryError(provider_code=error_code)
        if "file" in lowered or "media" in lowered:
            raise InvalidMediaError(provider_code=error_code)
        raise InvalidMetadataError(provider_code=error_code)

    @staticmethod
    def _caption(request: PublishRequest) -> str:
        tags = " ".join(f"#{item.lstrip('#')}" for item in request.hashtags)
        return "\n\n".join(item for item in (request.caption, tags) if item).strip()

    @staticmethod
    def _text(request: PublishRequest) -> str:
        tags = " ".join(f"#{item.lstrip('#')}" for item in request.hashtags)
        return "\n\n".join(
            item for item in (request.title, request.description or request.caption, tags) if item
        ).strip()
