from functools import lru_cache
from typing import Annotated

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
    telegram_allowed_user_ids: Annotated[list[int], NoDecode] = Field(default_factory=list)
    backend_url: str = "http://api:8000"

    ai_provider: str = "mock"
    ai_base_url: str = "http://host.docker.internal:1234/v1"
    ai_api_key: str = "lm-studio"
    ai_model: str = "local-model"
    ai_timeout_seconds: float = 120
    ai_max_retries: int = 2

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

    @field_validator("telegram_allowed_user_ids", mode="before")
    @classmethod
    def parse_user_ids(cls, value: object) -> object:
        if isinstance(value, str):
            if not value.strip():
                return []
            return [int(item.strip()) for item in value.split(",")]
        return value

    @model_validator(mode="after")
    def video_duration_range_is_valid(self) -> "Settings":
        if self.video_max_duration <= self.video_min_duration:
            raise ValueError("VIDEO_MAX_DURATION must be greater than VIDEO_MIN_DURATION")
        if self.pause_keep_padding * 2 >= self.pause_min_duration:
            raise ValueError("PAUSE_KEEP_PADDING must preserve a removable pause interior")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
