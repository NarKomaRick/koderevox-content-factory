import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import FramingMode, SubtitlePreset, VideoProjectStatus


class EditPace(StrEnum):
    CALM = "calm"
    MEDIUM = "medium"
    FAST = "fast"


class ClipPurpose(StrEnum):
    HOOK = "hook"
    CONTEXT = "context"
    MAIN = "main"
    EXAMPLE = "example"
    CONCLUSION = "conclusion"


class VideoConcept(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    hook: str = Field(min_length=3, max_length=300)
    focus: str = Field(min_length=3, max_length=500)
    target_duration: float = Field(ge=5, le=75)
    framing: FramingMode = FramingMode.CENTER_CROP
    pace: EditPace = EditPace.MEDIUM


class VideoConceptBatch(BaseModel):
    concepts: list[VideoConcept] = Field(min_length=3, max_length=3)

    @model_validator(mode="after")
    def concepts_are_distinct(self) -> "VideoConceptBatch":
        focuses = {concept.focus.strip().casefold() for concept in self.concepts}
        if len(focuses) != 3:
            raise ValueError("Video concepts must have genuinely different focuses")
        return self


class EditClip(BaseModel):
    source_start: float = Field(ge=0)
    source_end: float = Field(gt=0)
    source_segment_ids: list[int] = Field(min_length=1)
    purpose: ClipPurpose

    @model_validator(mode="after")
    def end_after_start(self) -> "EditClip":
        if self.source_end <= self.source_start:
            raise ValueError("clip end must be greater than start")
        if self.source_end - self.source_start < 0.3:
            raise ValueError("clips shorter than 300 ms are not allowed")
        if len(set(self.source_segment_ids)) != len(self.source_segment_ids):
            raise ValueError("source_segment_ids must be unique")
        if self.source_segment_ids != sorted(self.source_segment_ids):
            raise ValueError("source_segment_ids must be chronological")
        return self


class TextEmphasis(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = Field(min_length=1, max_length=120)

    @model_validator(mode="after")
    def end_after_start(self) -> "TextEmphasis":
        if self.end <= self.start:
            raise ValueError("emphasis end must be greater than start")
        return self


class ManualFraming(BaseModel):
    x: float = Field(default=0.5, ge=0, le=1)
    y: float = Field(default=0.5, ge=0, le=1)
    zoom: float = Field(default=1.0, ge=1, le=3)


class EditPlan(BaseModel):
    clips: list[EditClip] = Field(min_length=1)
    hook_text: str = Field(min_length=3, max_length=160)
    emphasis: list[TextEmphasis] = Field(default_factory=list)
    recommended_duration: float = Field(ge=1, le=180)
    reasoning_summary: str = Field(min_length=3, max_length=1000)
    framing: FramingMode = FramingMode.CENTER_CROP
    pace: EditPace = EditPace.MEDIUM
    manual_framing: ManualFraming | None = None

    @model_validator(mode="after")
    def clips_do_not_overlap(self) -> "EditPlan":
        for previous, current in zip(self.clips, self.clips[1:], strict=False):
            if current.source_start < previous.source_end:
                raise ValueError("source clips must be chronological and must not overlap")
        if self.framing == FramingMode.MANUAL and self.manual_framing is None:
            raise ValueError("manual framing settings are required")
        return self


class OverlayAssetType(StrEnum):
    IMAGE = "image"
    VIDEO = "video"
    SCREEN_RECORDING = "screen_recording"
    CODE = "code"
    SCREENSHOT = "screenshot"


class OverlayAsset(BaseModel):
    """Reserved declarative input for Phase 4; no AI B-roll generation in Phase 3."""

    type: OverlayAssetType
    storage_path: str
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    position: str = "center"

    @model_validator(mode="after")
    def valid_range(self) -> "OverlayAsset":
        if self.end <= self.start:
            raise ValueError("overlay end must be greater than start")
        return self


class VideoProjectCreate(BaseModel):
    content_draft_id: uuid.UUID | None = None
    target_duration: float = Field(default=45, ge=5, le=75)


class GenerateEditPlanRequest(BaseModel):
    concept_index: int = Field(default=0, ge=0, le=2)
    instruction: str | None = Field(default=None, min_length=2, max_length=2000)


class ManualClipRequest(BaseModel):
    source_start: float = Field(ge=0)
    source_end: float = Field(gt=0)
    hook_text: str | None = Field(default=None, max_length=160)
    framing: FramingMode = FramingMode.CENTER_CROP

    @model_validator(mode="after")
    def end_after_start(self) -> "ManualClipRequest":
        if self.source_end <= self.source_start:
            raise ValueError("source_end must be greater than source_start")
        return self


class EditPlanPatch(BaseModel):
    edit_plan: EditPlan


class StyleUpdate(BaseModel):
    preset: SubtitlePreset


class TranscriptOverrideUpdate(BaseModel):
    replacements: dict[str, str] = Field(max_length=100)

    @model_validator(mode="after")
    def replacements_are_conservative(self) -> "TranscriptOverrideUpdate":
        if any(not old.strip() or not new.strip() for old, new in self.replacements.items()):
            raise ValueError("replacement phrases cannot be blank")
        return self


class RenderRequest(BaseModel):
    force: bool = False


class RenderEnqueueResponse(BaseModel):
    task_id: str
    queued: bool


class VideoProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    source_item_id: uuid.UUID
    content_draft_id: uuid.UUID | None
    format: str
    status: VideoProjectStatus
    target_duration: float
    aspect_ratio: str
    source_start: float | None
    source_end: float | None
    concepts: list[dict[str, Any]]
    selected_concept: int | None
    edit_plan: dict[str, Any]
    visual_plan: dict[str, Any]
    subtitle_style: dict[str, Any]
    render_settings: dict[str, Any]
    transcript_overrides: dict[str, str]
    preview_path: str | None
    final_path: str | None
    render_error: str | None
    render_task_id: str | None
    render_fingerprint: str | None
    metrics: dict[str, Any]
    selected_thumbnail_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class ApprovedPackage(BaseModel):
    video_project_id: uuid.UUID
    video_path: str
    thumbnail_path: str | None
    title: str
    caption: str
    description: str
    platform_adaptations: dict[str, Any] = Field(default_factory=dict)
    project_id: uuid.UUID
    publishing_metadata: dict[str, Any] = Field(default_factory=dict)
