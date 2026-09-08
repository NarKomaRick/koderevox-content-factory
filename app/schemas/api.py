import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import (
    ContentFormat,
    ContentPillar,
    DraftStatus,
    IdeaStatus,
    Platform,
    ProcessingStage,
    SourceStatus,
    SourceType,
)


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ProjectCreate(BaseModel):
    name: str
    description: str = ""
    brand_context: str = ""
    target_audience: str = ""
    language: str = "ru"
    vocabulary: list[str] = Field(default_factory=list)
    allow_external_vision: bool = False
    brand_preset: dict[str, Any] = Field(default_factory=dict)


class ProjectRead(ProjectCreate, ORMModel):
    id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class ProjectUpdate(BaseModel):
    allow_external_vision: bool | None = None
    brand_preset: dict[str, Any] | None = None


class SourceCreate(BaseModel):
    project_id: uuid.UUID | None = None
    telegram_user_id: int
    telegram_username: str | None = None
    type: SourceType = SourceType.TEXT
    original_text: str | None = None
    transcript: str | None = None
    telegram_file_id: str | None = None
    telegram_unique_file_id: str | None = None
    telegram_chat_id: int | None = None
    telegram_message_id: int | None = None
    telegram_update_id: int | None = None
    local_file_path: str | None = None
    mime_type: str | None = None
    file_size: int | None = Field(default=None, ge=0)
    original_filename: str | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    type: SourceType
    original_text: str | None
    transcript: str | None
    telegram_file_id: str | None
    telegram_unique_file_id: str | None
    telegram_chat_id: int | None
    telegram_message_id: int | None
    telegram_update_id: int | None
    local_file_path: str | None
    processed_file_path: str | None
    mime_type: str | None
    file_size: int | None
    original_filename: str | None
    duration_seconds: float | None
    source_metadata: dict[str, Any]
    processing_status: SourceStatus
    processing_stage: ProcessingStage
    processing_error: str | None
    transcript_language: str | None
    transcript_segments: list[dict[str, Any]]
    extracted_text: str | None
    summary: str | None
    topic: str | None
    content_potential_score: int | None
    content_analysis: dict[str, Any]
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class TelegramIngestionResponse(BaseModel):
    source: SourceRead
    created: bool
    task_id: str | None = None


class EnqueueResponse(BaseModel):
    task_id: str
    queued: bool = True


class SourceNoteCreate(BaseModel):
    telegram_user_id: int
    text: str | None = Field(default=None, min_length=1, max_length=20_000)
    telegram_file_id: str | None = None
    telegram_unique_file_id: str | None = None
    telegram_update_id: int | None = None
    mime_type: str | None = None
    file_size: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def has_content(self) -> "SourceNoteCreate":
        if not self.text and not self.telegram_file_id:
            raise ValueError("Source note requires text or Telegram media")
        return self


class SourceNoteRead(ORMModel):
    id: uuid.UUID
    source_item_id: uuid.UUID
    user_id: uuid.UUID
    text: str | None
    transcript: str | None
    telegram_file_id: str | None
    local_file_path: str | None
    created_at: datetime


class InboxPage(BaseModel):
    items: list[SourceRead]
    total: int
    page: int
    page_size: int
    pages: int


class DailyDigest(BaseModel):
    total: int
    best: list[SourceRead]
    recommended_format_counts: dict[str, int]


class IdeaRead(ORMModel):
    id: uuid.UUID
    project_id: uuid.UUID
    source_item_id: uuid.UUID | None
    title: str
    description: str
    angle: str
    suggested_hook: str
    suggested_format: ContentFormat
    estimated_duration: int
    target_audience: str
    content_pillar: ContentPillar
    status: IdeaStatus
    score: float | None
    created_at: datetime


class SceneRead(BaseModel):
    start_second: int
    end_second: int
    spoken_text: str
    on_screen: str


class DraftRead(ORMModel):
    id: uuid.UUID
    idea_id: uuid.UUID
    platform: Platform
    format: ContentFormat
    hook: str
    script: str
    scene_breakdown: list[dict[str, Any]]
    caption: str
    title: str
    description: str
    call_to_action: str
    estimated_duration: int | None
    status: DraftStatus
    llm_metadata: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DraftStatusUpdate(BaseModel):
    status: DraftStatus
