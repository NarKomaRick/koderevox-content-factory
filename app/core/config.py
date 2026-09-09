from functools import lru_cache
from typing import Annotated
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "development"
    log_level: str = "INFO"
    database_url: str = (
        "postgresql+asyncpg://content_factory:content_factory@postgres:5432/content_factory"
    )
    redis_url: str = "redis://redis:6379/0"
    celery_task_always_eager: bool = False

    telegram_bot_token: str = ""
    telegram_proxy_url: str = ""
    telegram_allowed_user_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    telegram_publish_bot_token: str = ""
    backend_url: str = "http://api:8000"
    default_timezone: str = "Europe/Moscow"

    ai_provider: str = "mock"
    ai_base_url: str = "http://host.docker.internal:1234/v1"
    ai_api_key: str = "lm-studio"
    ai_model: str = "local-model"
    ai_timeout_seconds: float = 120
    ai_max_retries: int = 2
    ai_max_tokens: int = Field(default=1536, ge=64, le=32768)

    tts_provider: str = "espeak"
    tts_language: str = "ru"
    tts_voice: str = ""
    tts_rate: int | None = None
    tts_volume: int | None = None

    stt_provider: str = "faster_whisper"
    stt_model: str = "small"
    stt_device: str = "cpu"
    stt_compute_type: str = "int8"
    media_root: str = "/data/media"
    max_media_size_mb: int = 200
    link_fetch_timeout_seconds: float = 15
    link_max_size_mb: int = 10
    link_max_redirects: int = 5
    document_max_chars: int = 100_000

    video_width: int = Field(default=1080, ge=240, le=4320, multiple_of=2)
    video_height: int = Field(default=1920, ge=240, le=4320, multiple_of=2)
    video_fps: int = Field(default=30, ge=15, le=60)
    video_crf: int = Field(default=20, ge=0, le=51)
    video_preset: str = "medium"
    video_encoder: str = "libx264"
    video_min_duration: float = Field(default=5.0, gt=0)
    video_max_duration: float = Field(default=75.0, gt=0)
    pause_removal_enabled: bool = True
    pause_min_duration: float = Field(default=0.65, gt=0)
    pause_keep_padding: float = Field(default=0.12, ge=0)
    pause_noise_db: float = -35.0
    audio_normalization_enabled: bool = True
    audio_noise_reduction_enabled: bool = False
    hook_overlay_enabled: bool = True
    render_temp_root: str = "/tmp/content-factory/render"
    telegram_preview_max_size_mb: int = Field(default=48, gt=0)
    celery_render_concurrency: int = Field(default=1, ge=1, le=16)
    video_font_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"

    vision_enabled: bool = False
    vision_provider: str = "openai_compatible"
    vision_base_url: str = ""
    vision_api_key: str = ""
    vision_model: str = ""
    vision_timeout_seconds: float = Field(default=120, gt=0)
    ocr_enabled: bool = True
    ocr_language: str = "rus+eng"
    max_image_pixels: int = Field(default=40_000_000, ge=1_000_000)
    max_asset_size_mb: int = Field(default=200, ge=1)
    max_asset_duration: float = Field(default=600, gt=0)
    visual_min_insert_duration: float = Field(default=1.5, gt=0)
    visual_max_insert_duration: float = Field(default=8.0, gt=0)
    visual_min_gap_seconds: float = Field(default=2.0, ge=0)
    visual_max_inserts_per_minute: int = Field(default=10, ge=1, le=60)
    visual_safe_margin_top: int = Field(default=140, ge=0)
    visual_safe_margin_bottom: int = Field(default=360, ge=0)
    thumbnail_width: int = Field(default=1280, ge=320, le=4096)
    thumbnail_height: int = Field(default=720, ge=180, le=4096)
    assembly_target_visual_change_min_seconds: float = Field(default=3.0, gt=0)
    assembly_target_visual_change_max_seconds: float = Field(default=6.0, gt=0)
    assembly_max_screenshot_seconds: float = Field(default=8.0, gt=0)
    preview_width: int = Field(default=720, ge=240, le=2160, multiple_of=2)
    preview_height: int = Field(default=1280, ge=240, le=3840, multiple_of=2)
    preview_crf: int = Field(default=27, ge=0, le=51)
    preview_preset: str = "veryfast"
    initial_owner_telegram_id: int | None = None
    app_master_key: str = ""
    setup_sensitive_rate_limit_seconds: int = Field(default=10, ge=1, le=3600)

    publish_scheduler_interval_seconds: int = Field(default=30, ge=1, le=3600)
    publish_max_attempts: int = Field(default=5, ge=1, le=20)
    celery_publish_concurrency: int = Field(default=2, ge=1, le=32)
    publish_retry_delays_seconds: Annotated[list[int], NoDecode] = Field(
        default_factory=lambda: [60, 300, 900, 3600]
    )
    credential_encryption_key: str = ""
    youtube_client_id: str = ""
    youtube_client_secret: str = ""
    youtube_redirect_uri: str = ""
    tiktok_client_key: str = ""
    tiktok_client_secret: str = ""
    tiktok_redirect_uri: str = ""
    tiktok_webhook_tolerance_seconds: int = Field(default=300, ge=30, le=3600)

    @field_validator("telegram_allowed_user_ids", mode="before")
    @classmethod
    def parse_user_ids(cls, value: object) -> object:
        if isinstance(value, str):
            if not value.strip():
                return []
            return [int(item.strip()) for item in value.split(",")]
        return value

    @field_validator("publish_retry_delays_seconds", mode="before")
    @classmethod
    def parse_retry_delays(cls, value: object) -> object:
        if isinstance(value, str):
            return [int(item.strip()) for item in value.split(",") if item.strip()]
        return value

    @field_validator("default_timezone")
    @classmethod
    def valid_default_timezone(cls, value: str) -> str:
        try:
            ZoneInfo(value)
        except ZoneInfoNotFoundError as exc:
            raise ValueError("DEFAULT_TIMEZONE must be a valid IANA timezone") from exc
        return value

    @model_validator(mode="after")
    def video_duration_range_is_valid(self) -> "Settings":
        if self.video_max_duration <= self.video_min_duration:
            raise ValueError("VIDEO_MAX_DURATION must be greater than VIDEO_MIN_DURATION")
        if self.pause_keep_padding * 2 >= self.pause_min_duration:
            raise ValueError("PAUSE_KEEP_PADDING must preserve a removable pause interior")
        if self.visual_max_insert_duration < self.visual_min_insert_duration:
            raise ValueError("VISUAL_MAX_INSERT_DURATION must be >= VISUAL_MIN_INSERT_DURATION")
        if (
            self.assembly_target_visual_change_max_seconds
            < self.assembly_target_visual_change_min_seconds
        ):
            raise ValueError("ASSEMBLY visual change max must be >= min")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
