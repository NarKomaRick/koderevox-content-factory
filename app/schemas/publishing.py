from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.enums import (
    PublicationAttemptStatus,
    PublicationEventType,
    PublicationStatus,
    PublishingPlatform,
    PublishPackageStatus,
)


def _reject_plaintext_credentials(value: object) -> None:
    forbidden = {
        "access_token",
        "refresh_token",
        "bot_token",
        "client_secret",
        "oauth_secret",
        "credential",
        "credentials",
    }
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in forbidden:
                raise ValueError("Credentials must use encrypted storage or ENV")
            _reject_plaintext_credentials(item)
    elif isinstance(value, list):
        for item in value:
            _reject_plaintext_credentials(item)


class PlatformAdaptationOutput(BaseModel):
    title: str = Field(max_length=500)
    caption: str = Field(max_length=5000)
    description: str = Field(max_length=10_000)
    hashtags: list[str] = Field(default_factory=list, max_length=30)
    call_to_action: str = Field(default="", max_length=1000)

    @field_validator("hashtags")
    @classmethod
    def normalize_hashtags(cls, value: list[str]) -> list[str]:
        result: list[str] = []
        for item in value:
            normalized = item.strip().lstrip("#").replace(" ", "")
            if normalized and normalized not in result:
                result.append(normalized)
        return result


class PlatformMediaProfile(BaseModel):
    platform: PublishingPlatform
    container: str = "mp4"
    video_codec: str = "h264"
    audio_codec: str = "aac"
    vertical_allowed: bool = True
    thumbnail_optional: bool = True
    max_title_length: int
    max_caption_length: int
    max_description_length: int
    max_file_size_bytes: int | None = None
    requires_clean_render: bool = False


class PublishPackageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    content_draft_id: uuid.UUID | None
    video_project_id: uuid.UUID | None
    thumbnail_project_id: uuid.UUID | None
    status: PublishPackageStatus
    master_video_path: str | None
    master_thumbnail_path: str | None
    base_title: str
    base_caption: str
    base_description: str
    package_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class PlatformVariantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    publish_package_id: uuid.UUID
    platform: PublishingPlatform
    video_path: str | None
    thumbnail_path: str | None
    title: str
    caption: str
    description: str
    hashtags: list[str]
    settings: dict[str, Any]
    media_profile: dict[str, Any]
    revision: int
    content_hash: str
    created_at: datetime
    updated_at: datetime


class PlatformVariantUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    caption: str | None = Field(default=None, max_length=5000)
    description: str | None = Field(default=None, max_length=10_000)
    hashtags: list[str] | None = Field(default=None, max_length=30)
    settings: dict[str, Any] | None = None


class PackagePrepareRequest(BaseModel):
    platforms: list[PublishingPlatform] = Field(
        default_factory=lambda: list(PublishingPlatform), min_length=1
    )
    regenerate: bool = False


class PackageWithVariants(BaseModel):
    package: PublishPackageRead
    variants: list[PlatformVariantRead]


class PlatformAccountCreate(BaseModel):
    project_id: uuid.UUID
    platform: PublishingPlatform
    display_name: str = Field(min_length=1, max_length=255)
    external_account_id: str | None = Field(default=None, max_length=512)
    username: str | None = Field(default=None, max_length=255)
    capabilities: dict[str, Any] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def credentials_are_not_plaintext(self) -> PlatformAccountCreate:
        _reject_plaintext_credentials(self.settings)
        _reject_plaintext_credentials(self.capabilities)
        return self


class PlatformAccountUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    external_account_id: str | None = Field(default=None, max_length=512)
    username: str | None = Field(default=None, max_length=255)
    is_active: bool | None = None
    capabilities: dict[str, Any] | None = None
    settings: dict[str, Any] | None = None

    @model_validator(mode="after")
    def credentials_are_not_plaintext(self) -> PlatformAccountUpdate:
        _reject_plaintext_credentials(self.settings or {})
        _reject_plaintext_credentials(self.capabilities or {})
        return self


class PlatformAccountRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    platform: PublishingPlatform
    display_name: str
    external_account_id: str | None
    username: str | None
    is_active: bool
    capabilities: dict[str, Any]
    settings: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class PublicationCreate(BaseModel):
    platform_variant_id: uuid.UUID
    platform_account_id: uuid.UUID
    scheduled_at: datetime | None = None
    publish_now: bool = False
    idempotency_key: str | None = Field(default=None, max_length=255)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def choose_time_or_now(self) -> PublicationCreate:
        if self.publish_now and self.scheduled_at is not None:
            raise ValueError("Choose either publish_now or scheduled_at")
        if self.scheduled_at is not None and self.scheduled_at.tzinfo is None:
            raise ValueError("scheduled_at must be timezone-aware")
        return self


class PublicationBatchCreate(BaseModel):
    items: list[PublicationCreate] = Field(min_length=1, max_length=20)


class PublicationBatchResponse(BaseModel):
    publications: list[PublicationRead]
    validation: list[PlatformValidationResult]


class PublicationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    publish_package_id: uuid.UUID
    platform_variant_id: uuid.UUID
    platform_account_id: uuid.UUID
    platform: PublishingPlatform
    status: PublicationStatus
    scheduled_at: datetime | None
    next_retry_at: datetime | None
    started_at: datetime | None
    published_at: datetime | None
    remote_id: str | None
    remote_url: str | None
    attempt_count: int
    last_error_code: str | None
    last_error_message: str | None
    publication_metadata: dict[str, Any]
    variant_snapshot: dict[str, Any]
    variant_hash: str
    media_hash: str | None
    task_id: str | None
    created_at: datetime
    updated_at: datetime


class PublicationReschedule(BaseModel):
    scheduled_at: datetime

    @field_validator("scheduled_at")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("scheduled_at must be timezone-aware")
        return value


class PublicationAttemptRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    publication_id: uuid.UUID
    attempt_number: int
    started_at: datetime
    finished_at: datetime | None
    status: PublicationAttemptStatus
    provider_error_code: str | None
    sanitized_error: str | None
    provider_request_id: str | None
    media_hash: str | None
    attempt_metadata: dict[str, Any]


class PublicationEventRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    publication_id: uuid.UUID
    event_type: PublicationEventType
    details: dict[str, Any]
    created_at: datetime


class PublicationDetail(BaseModel):
    publication: PublicationRead
    attempts: list[PublicationAttemptRead]
    events: list[PublicationEventRead]


class ValidationIssue(BaseModel):
    code: str
    message: str
    severity: Literal["warning", "error"] = "error"


class PlatformValidationResult(BaseModel):
    platform: PublishingPlatform
    ready: bool
    issues: list[ValidationIssue] = Field(default_factory=list)
    capabilities: dict[str, Any] = Field(default_factory=dict)


class PublishRequest(BaseModel):
    publication_id: uuid.UUID
    platform: PublishingPlatform
    video_path: str | None
    thumbnail_path: str | None
    title: str
    caption: str
    description: str
    hashtags: list[str]
    settings: dict[str, Any]
    media_hash: str | None
    remote_id: str | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)


class PublisherContext(BaseModel):
    account_id: uuid.UUID
    external_account_id: str | None
    username: str | None
    settings: dict[str, Any]
    capabilities: dict[str, Any]
    credentials: dict[str, Any] = Field(default_factory=dict, exclude=True, repr=False)


class PublishResult(BaseModel):
    remote_id: str
    remote_url: str | None = None
    status: Literal["processing", "published", "published_with_warning"] = "published"
    provider_request_id: str | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    warning: str | None = None


class ProviderStatusResult(BaseModel):
    status: Literal["processing", "published", "failed"]
    remote_id: str | None = None
    remote_url: str | None = None
    provider_metadata: dict[str, Any] = Field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None


class VariantMediaPrepareResponse(BaseModel):
    variant: PlatformVariantRead
    queued: bool
    task_id: str | None = None


class OAuthStartResponse(BaseModel):
    authorization_url: str
    expires_at: datetime


class OAuthCallbackResponse(BaseModel):
    platform_account_id: uuid.UUID
    platform: PublishingPlatform
    connected: bool = True
