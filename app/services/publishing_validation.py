import uuid
from pathlib import Path
from typing import Any, Protocol

from app.models import PlatformAccount
from app.models.entities import PlatformVariant
from app.schemas.publishing import (
    PlatformValidationResult,
    PublisherContext,
    PublishRequest,
    ValidationIssue,
)
from app.services.media import FFmpegMediaProcessor, MediaProcessingError
from app.services.platform_profiles import PlatformMediaProfiles
from app.services.publishers.registry import PublisherRegistry
from app.services.publishing_errors import PublishingError


class PublishingValidationService:
    def __init__(
        self,
        registry: PublisherRegistry,
        *,
        media_root: str = "/data/media",
        credential_reader: "ValidationCredentialReader | None" = None,
        media_processor: FFmpegMediaProcessor | None = None,
    ) -> None:
        self.registry = registry
        self.media_root = Path(media_root)
        self.profiles = PlatformMediaProfiles()
        self.credential_reader = credential_reader
        self.media_processor = media_processor or FFmpegMediaProcessor()

    async def validate(
        self,
        variant: PlatformVariant,
        account: PlatformAccount,
        *,
        credentials: dict[str, object] | None = None,
    ) -> PlatformValidationResult:
        issues: list[ValidationIssue] = []
        if not account.is_active:
            issues.append(ValidationIssue(code="ACCOUNT_INACTIVE", message="Аккаунт отключён."))
        if account.platform != variant.platform:
            issues.append(
                ValidationIssue(code="PLATFORM_MISMATCH", message="Выбран аккаунт другой площадки.")
            )
        profile = self.profiles.get(variant.platform)
        media = self.resolve(variant.video_path)
        if media is not None:
            if not media.is_file():
                issues.append(ValidationIssue(code="INVALID_MEDIA", message="Видео не найдено."))
            elif profile.max_file_size_bytes and media.stat().st_size > profile.max_file_size_bytes:
                issues.append(
                    ValidationIssue(code="INVALID_MEDIA", message="Видео превышает лимит площадки.")
                )
            elif media.suffix.lower() != f".{profile.container}":
                issues.append(ValidationIssue(code="INVALID_MEDIA", message="Нужен MP4-контейнер."))
            else:
                try:
                    metadata = self.media_processor.useful_metadata(
                        await self.media_processor.probe(media)
                    )
                    if metadata.get("video_codec") != profile.video_codec:
                        issues.append(
                            ValidationIssue(code="INVALID_MEDIA", message="Нужен H.264 video.")
                        )
                    if metadata.get("audio_codec") not in {None, profile.audio_codec}:
                        issues.append(
                            ValidationIssue(code="INVALID_MEDIA", message="Нужен AAC audio.")
                        )
                except (MediaProcessingError, ValueError, OSError):
                    issues.append(
                        ValidationIssue(code="INVALID_MEDIA", message="FFprobe отклонил медиа.")
                    )
        if profile.max_title_length and len(variant.title) > profile.max_title_length:
            issues.append(
                ValidationIssue(code="INVALID_METADATA", message="Заголовок слишком длинный.")
            )
        if profile.max_caption_length and len(variant.caption) > profile.max_caption_length:
            issues.append(
                ValidationIssue(code="INVALID_METADATA", message="Caption слишком длинный.")
            )
        if (
            profile.max_description_length
            and len(variant.description) > profile.max_description_length
        ):
            issues.append(
                ValidationIssue(code="INVALID_METADATA", message="Описание слишком длинное.")
            )
        if not self.registry.supports(variant.platform):
            issues.append(
                ValidationIssue(code="PUBLISHER_NOT_CONFIGURED", message="Publisher не настроен.")
            )
        if issues:
            return PlatformValidationResult(
                platform=variant.platform,
                ready=False,
                issues=issues,
                capabilities=account.capabilities,
            )
        publisher = self.registry.get(variant.platform)
        if credentials is None and self.credential_reader is not None:
            credentials = await self.credential_reader.get(account.id)
        request = self.request_from_variant(variant)
        context = PublisherContext(
            account_id=account.id,
            external_account_id=account.external_account_id,
            username=account.username,
            settings=account.settings,
            capabilities=account.capabilities,
            credentials=credentials or {},
        )
        try:
            return await publisher.validate(request, context)
        except PublishingError as exc:
            return PlatformValidationResult(
                platform=variant.platform,
                ready=False,
                issues=[ValidationIssue(code=exc.code, message=exc.user_message)],
                capabilities=account.capabilities,
            )

    def request_from_variant(self, variant: PlatformVariant) -> PublishRequest:
        return PublishRequest(
            publication_id=variant.id,
            platform=variant.platform,
            video_path=str(self.resolve(variant.video_path)) if variant.video_path else None,
            thumbnail_path=(
                str(self.resolve(variant.thumbnail_path)) if variant.thumbnail_path else None
            ),
            title=variant.title,
            caption=variant.caption,
            description=variant.description,
            hashtags=variant.hashtags,
            settings=variant.settings,
            media_hash=None,
        )

    def resolve(self, value: str | None) -> Path | None:
        if value is None:
            return None
        path = Path(value)
        return path if path.is_absolute() else self.media_root / path


class ValidationCredentialReader(Protocol):
    async def get(self, platform_account_id: uuid.UUID) -> dict[str, Any]: ...
