import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import (
    ProductionFactStatus,
    ProductionMaterialRole,
    ProductionStatus,
    ScriptSource,
    TimelineTrack,
    VoiceoverStatus,
)


class ProductionProjectCreate(BaseModel):
    project_id: uuid.UUID
    user_id: uuid.UUID
    initial_source_item_id: uuid.UUID | None = None
    title: str = Field(min_length=2, max_length=500)
    target_format: str = Field(default="short_video", max_length=64)
    target_duration: float | None = Field(default=None, ge=5, le=3600)


class ProductionProjectPatch(BaseModel):
    working_title: str | None = Field(default=None, min_length=1, max_length=500)
    target_format: str | None = Field(default=None, max_length=64)
    target_duration: float | None = Field(default=None, ge=5, le=3600)
    status: ProductionStatus | None = None
    persistent_instructions: list[str] | None = Field(default=None, max_length=100)


class ProductionProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    initial_source_item_id: uuid.UUID | None
    title: str
    working_title: str
    status: ProductionStatus
    target_format: str
    target_duration: float | None
    current_script_version_id: uuid.UUID | None
    approved_script_version_id: uuid.UUID | None
    primary_voiceover_id: uuid.UUID | None
    active_video_project_id: uuid.UUID | None
    active_timeline_revision_id: uuid.UUID | None
    production_context: dict[str, Any]
    persistent_instructions: list[str]
    created_at: datetime
    updated_at: datetime


class MaterialAttach(BaseModel):
    source_item_id: uuid.UUID | None = None
    asset_id: uuid.UUID | None = None
    roles: list[ProductionMaterialRole] = Field(default_factory=list)
    user_instruction: str | None = Field(default=None, max_length=4000)
    is_user_locked: bool = False

    @model_validator(mode="after")
    def exactly_one_source(self) -> "MaterialAttach":
        if (self.source_item_id is None) == (self.asset_id is None):
            raise ValueError("exactly one of source_item_id or asset_id is required")
        return self


class ProductionMaterialRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    production_project_id: uuid.UUID
    source_item_id: uuid.UUID | None
    asset_id: uuid.UUID | None
    roles: list[str]
    user_instruction: str | None
    is_user_locked: bool
    is_used: bool
    created_at: datetime
    updated_at: datetime


class FactCreate(BaseModel):
    text: str = Field(min_length=2, max_length=10_000)
    source_item_id: uuid.UUID | None = None
    source_url: str | None = Field(default=None, max_length=2048)
    status: ProductionFactStatus = ProductionFactStatus.PROPOSED


class ScriptVersionCreate(BaseModel):
    content: str = Field(min_length=3, max_length=100_000)
    structured_sections: list[dict[str, Any]] = Field(default_factory=list)
    source: ScriptSource = ScriptSource.USER
    user_instruction: str | None = Field(default=None, max_length=10_000)


class ScriptGeneration(BaseModel):
    content: str = Field(min_length=3, max_length=100_000)
    sections: list[dict[str, Any]] = Field(min_length=1)


class ScriptVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    production_project_id: uuid.UUID
    version_number: int
    content: str
    structured_sections: list[dict[str, Any]]
    source: ScriptSource
    user_instruction: str | None
    diff: dict[str, Any]
    created_at: datetime
    approved_at: datetime | None


class AlignmentRange(BaseModel):
    section_id: str
    script_text: str
    voice_text: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    confidence: float = Field(ge=0, le=1)


class ScriptAlignment(BaseModel):
    sections: list[AlignmentRange]
    overall_confidence: float = Field(ge=0, le=1)
    unmatched_script: list[str] = Field(default_factory=list)
    extra_spoken: list[str] = Field(default_factory=list)


class VoiceoverRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    production_project_id: uuid.UUID
    source_item_id: uuid.UUID
    original_path: str
    processed_path: str
    duration: float
    language: str | None
    transcript: str
    segments: list[dict[str, Any]]
    words: list[dict[str, Any]]
    script_version_id: uuid.UUID | None
    alignment: dict[str, Any]
    alignment_score: float | None
    status: VoiceoverStatus


class TimelineItem(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    track: TimelineTrack
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    asset_id: uuid.UUID | None = None
    text: str | None = None
    layout: str = "fullscreen"
    source_start: float | None = Field(default=None, ge=0)
    source_end: float | None = Field(default=None, gt=0)
    locked_by_user: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_range(self) -> "TimelineItem":
        if self.end <= self.start:
            raise ValueError("timeline item end must be greater than start")
        if self.source_end is not None and self.source_start is not None:
            if self.source_end <= self.source_start:
                raise ValueError("source_end must be greater than source_start")
        return self


class ProductionTimeline(BaseModel):
    duration: float = Field(gt=0)
    voiceover_track_id: uuid.UUID
    items: list[TimelineItem]
    profile: str = "preview"

    @model_validator(mode="after")
    def items_fit_master(self) -> "ProductionTimeline":
        if any(item.end > self.duration + 0.05 for item in self.items):
            raise ValueError("timeline items cannot exceed voiceover duration")
        return self


class PlacementCandidate(BaseModel):
    start: float
    end: float
    text: str
    confidence: float = Field(ge=0, le=1)


class PlacementResult(BaseModel):
    status: str
    candidates: list[PlacementCandidate]


class TimelineRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    production_project_id: uuid.UUID
    revision_number: int
    timeline_json: dict[str, Any]
    user_instruction: str | None
    change_summary: str | None
    created_at: datetime


class ScriptEditRequest(BaseModel):
    instruction: str = Field(min_length=2, max_length=10_000)


class PlacementRequest(BaseModel):
    material_id: uuid.UUID
    instruction: str = Field(min_length=2, max_length=4000)
    candidate_index: int | None = Field(default=None, ge=0, le=2)


class PlacementSelection(BaseModel):
    candidate_index: int = Field(ge=0, le=2)


class ReplanRequest(BaseModel):
    instruction: str = Field(min_length=2, max_length=4000)


class RuntimeSettingUpdate(BaseModel):
    telegram_user_id: int
    private_chat: bool = True
    key: str = Field(min_length=2, max_length=255)
    value: Any


class SecretUpdate(BaseModel):
    telegram_user_id: int
    private_chat: bool = True
    name: str = Field(min_length=2, max_length=255)
    value: str = Field(min_length=1, max_length=20_000)


class AISetupRequest(BaseModel):
    telegram_user_id: int
    private_chat: bool = True
    provider: str = "openai_compatible"
    base_url: str = Field(min_length=8, max_length=2048)
    model: str = Field(min_length=1, max_length=500)
    api_key: str | None = Field(default=None, max_length=20_000)


class RenderProfile(BaseModel):
    name: str
    width: int
    height: int
    crf: int
    preset: str
    audio_bitrate: str


class GapWarning(BaseModel):
    start: float
    end: float
    duration: float
    reason: str
    recommendations: list[str]
