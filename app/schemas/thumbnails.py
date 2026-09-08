import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.enums import ThumbnailPreset, ThumbnailStatus


class ThumbnailConcept(BaseModel):
    headline: str = Field(min_length=2, max_length=80)
    background_asset_id: uuid.UUID | None = None
    subject_asset_id: uuid.UUID | None = None
    frame_path: str | None = Field(default=None, max_length=1024)
    composition: str = Field(default="subject_right", max_length=64)
    emphasis_words: list[str] = Field(default_factory=list, max_length=6)
    preset: ThumbnailPreset = ThumbnailPreset.TECH_DARK


class ThumbnailGenerateRequest(BaseModel):
    headline: str | None = Field(default=None, min_length=2, max_length=80)


class ThumbnailRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    video_project_id: uuid.UUID
    status: ThumbnailStatus
    concept: dict[str, Any]
    render_settings: dict[str, Any]
    output_path: str | None
    metrics: dict[str, Any]
    render_fingerprint: str | None
    created_at: datetime
    updated_at: datetime
