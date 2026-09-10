"""Public, provider-neutral schemas used by the Director tool protocol."""

from __future__ import annotations

import uuid
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class SafeZones(BaseModel):
    top: int = Field(default=160, ge=0)
    bottom: int = Field(default=360, ge=0)
    left: int = Field(default=70, ge=0)
    right: int = Field(default=70, ge=0)


class OutputProfile(BaseModel):
    """Physical output constraints. The model may select a profile, not its geometry."""

    model_config = ConfigDict(extra="forbid")

    platform: str = "youtube_shorts"
    width: int = Field(default=1080, ge=240, le=4320, multiple_of=2)
    height: int = Field(default=1920, ge=240, le=4320, multiple_of=2)
    fps: int = Field(default=30, ge=15, le=60)
    aspect_ratio: str = "9:16"
    max_duration: float = Field(default=60, gt=0, le=3600)
    safe_zones: SafeZones = Field(default_factory=SafeZones)
    subtitle_zone: SafeZones = Field(default_factory=lambda: SafeZones(top=0, bottom=360))
    logo_zone: SafeZones | None = None
    ui_obstruction_zones: list[NormalizedRegion] = Field(default_factory=list)
    recommended_text_sizes: dict[str, int] = Field(
        default_factory=lambda: {"title": 72, "body": 52, "caption": 44}
    )
    audio: dict[str, Any] = Field(default_factory=lambda: {"codec": "aac", "sample_rate": 48000})

    @classmethod
    def for_platform(
        cls, platform: str, *, width: int | None = None, height: int | None = None
    ) -> OutputProfile:
        key = platform.casefold()
        presets: dict[str, dict[str, Any]] = {
            "youtube_shorts": {
                "width": 1080,
                "height": 1920,
                "aspect_ratio": "9:16",
                "max_duration": 60,
            },
            "tiktok": {
                "width": 1080,
                "height": 1920,
                "aspect_ratio": "9:16",
                "max_duration": 60,
                "safe_zones": {"top": 180, "bottom": 420, "left": 70, "right": 70},
            },
            "instagram_reels": {
                "width": 1080,
                "height": 1920,
                "aspect_ratio": "9:16",
                "max_duration": 90,
                "safe_zones": {"top": 180, "bottom": 420, "left": 70, "right": 70},
            },
            "youtube_landscape": {
                "width": 1920,
                "height": 1080,
                "aspect_ratio": "16:9",
                "max_duration": 900,
                "safe_zones": {"top": 70, "bottom": 120, "left": 100, "right": 100},
            },
            "telegram": {"width": 1080, "height": 1920, "aspect_ratio": "9:16", "max_duration": 75},
        }
        values = presets.get(
            key, {"width": 1080, "height": 1920, "aspect_ratio": "9:16", "max_duration": 75}
        )
        if width is not None:
            values["width"] = width
        if height is not None:
            values["height"] = height
        values["platform"] = platform
        return cls.model_validate(values)


class NormalizedRegion(BaseModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def fits_canvas(self) -> NormalizedRegion:
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("region must fit normalized canvas")
        return self


Anchor = Literal[
    "top_left",
    "top_center",
    "top_right",
    "center",
    "bottom_left",
    "bottom_center",
    "bottom_right",
    "subject_left",
    "subject_right",
    "auto",
]


class AddVisualOperation(BaseModel):
    operation: Literal["add_visual"]
    asset_id: uuid.UUID
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    source_start: float | None = Field(default=None, ge=0)
    source_end: float | None = Field(default=None, gt=0)
    layout: str = Field(default="fullscreen", max_length=64)
    track: Literal["video_base", "broll", "overlay"] = "broll"
    locked_by_user: bool = False
    visual_intent: dict[str, Any] | None = None

    @model_validator(mode="after")
    def valid_range(self) -> AddVisualOperation:
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        if (
            self.source_start is not None
            and self.source_end is not None
            and self.source_end <= self.source_start
        ):
            raise ValueError("source_end must be greater than source_start")
        return self


class AddTextOperation(BaseModel):
    operation: Literal["add_text"]
    text: str = Field(min_length=1, max_length=500)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    anchor: Anchor = "auto"
    style: str = Field(default="accent", max_length=64)
    font_size: int | None = Field(default=None, ge=18, le=240)
    locked_by_user: bool = False
    semantic_role: Literal["headline", "caption", "callout", "label", "code", "subtitle", "cta"] = (
        "caption"
    )
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def valid_range(self) -> AddTextOperation:
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class AddGraphicOperation(BaseModel):
    operation: Literal["add_graphic"]
    kind: Literal[
        "text_card",
        "title_card",
        "stat_card",
        "quote",
        "badge",
        "callout",
        "lower_third",
        "code_card",
        "comparison_card",
        "warning_card",
        "timeline_graphic",
        "simple_diagram",
        "arrow",
        "circle_highlight",
        "rectangle_highlight",
    ]
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    content: dict[str, Any] = Field(default_factory=dict)
    style: str = Field(default="technical", max_length=64)
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def valid_range(self) -> AddGraphicOperation:
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        return self


class BlurRegionOperation(BaseModel):
    operation: Literal["blur_region"]
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    region: NormalizedRegion | None = None
    mode: Literal["background_blur", "region_blur", "privacy_blur", "focus_blur"] = "region_blur"
    strength: int = Field(default=20, ge=1, le=80)

    @model_validator(mode="after")
    def valid_range(self) -> BlurRegionOperation:
        if self.end <= self.start:
            raise ValueError("end must be greater than start")
        if self.mode != "background_blur" and self.region is None:
            raise ValueError("region is required for non-background blur")
        return self


class SetLayoutOperation(BaseModel):
    operation: Literal["set_layout"]
    timeline_item_id: uuid.UUID
    layout: str = Field(min_length=2, max_length=64)


class AddTransitionOperation(BaseModel):
    operation: Literal["add_transition"]
    timeline_item_id: uuid.UUID
    transition: Literal["none", "fade", "scale_in", "slide"]
    duration: float = Field(default=0.25, ge=0, le=2)


class AdjustAudioOperation(BaseModel):
    operation: Literal["adjust_audio"]
    mode: Literal[
        "normalize_voice",
        "gain",
        "fade_in",
        "fade_out",
        "duck_background",
        "mute_asset_audio",
        "mix_background",
    ]
    amount: float = Field(default=0, ge=-24, le=24)
    start: float | None = Field(default=None, ge=0)
    end: float | None = Field(default=None, gt=0)


class RemoveItemOperation(BaseModel):
    operation: Literal["remove_item"]
    timeline_item_id: uuid.UUID


TimelineOperation = Annotated[
    AddVisualOperation
    | AddTextOperation
    | AddGraphicOperation
    | BlurRegionOperation
    | SetLayoutOperation
    | AddTransitionOperation
    | AdjustAudioOperation
    | RemoveItemOperation,
    Field(discriminator="operation"),
]


class DirectorToolCall(BaseModel):
    id: str = Field(min_length=1, max_length=255)
    name: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any] = Field(default_factory=dict)


class DirectorToolResult(BaseModel):
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    error: dict[str, Any] | None = None


class DirectorTurn(BaseModel):
    reasoning: str = Field(default="", max_length=4000)
    tool_calls: list[DirectorToolCall] = Field(default_factory=list, max_length=8)
    finalize: bool = False


class DirectorRunRequest(BaseModel):
    instruction: str = Field(default="", max_length=10_000)
    output_profile: str | None = Field(default=None, max_length=64)


class DirectorInstructionRequest(BaseModel):
    instruction: str = Field(min_length=2, max_length=10_000)


class DirectorRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    production_project_id: uuid.UUID
    status: str
    instruction: str
    director_iteration: int
    step_count: int
    llm_call_count: int
    preview_count: int
    external_asset_count: int
    external_asset_bytes: int
    active: bool
    current_revision_id: uuid.UUID | None
    best_revision_id: uuid.UUID | None
    quality_report_json: dict[str, Any]
    story_analysis_json: dict[str, Any]
    director_plan_json: dict[str, Any]
    audio_intelligence_json: dict[str, Any]
    metrics_json: dict[str, Any]
    review_iterations: int
    variant_count: int
    error: str | None


class HookAnalysis(BaseModel):
    type: str = "opening_promise"
    message: str = ""
    strength: float = Field(default=0.5, ge=0, le=1)


class StoryBeat(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    purpose: str = "explanation"
    meaning: str = ""
    importance: float = Field(default=0.5, ge=0, le=1)
    viewer_state: str = "understanding"
    viewer_should_understand: str = ""
    viewer_should_feel: str = "curiosity"
    visual_need: str = "medium"
    visual_strategy: str = "specific relevant visual"
    energy: float = Field(default=0.5, ge=0, le=1)
    pacing: str = "medium"
    transition_intent: str = "hard_cut"

    @model_validator(mode="after")
    def valid_range(self) -> StoryBeat:
        if self.end <= self.start:
            raise ValueError("story beat end must be greater than start")
        return self


class StoryAnalysis(BaseModel):
    goal: str = ""
    audience: str = ""
    context: str = ""
    format: str = "short_video"
    core_message: str = ""
    conflict: str = ""
    tone: str = "clear, purposeful"
    complexity: Literal["low", "medium", "high"] = "medium"
    hook: HookAnalysis = Field(default_factory=HookAnalysis)
    causal_chain: list[str] = Field(default_factory=list, max_length=12)
    emotional_arc: list[str] = Field(default_factory=list, max_length=12)
    climax: str = ""
    cta: str = ""
    beats: list[StoryBeat] = Field(default_factory=list, max_length=100)


class PacingWindow(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    pace: Literal["very_slow", "slow", "medium", "medium_fast", "fast", "very_fast"] = "medium"
    reason: str = ""
    edit_density: Literal["low", "medium", "high"] = "medium"


class DirectorPlan(BaseModel):
    concept: str = ""
    visual_language: str = ""
    pacing_strategy: str = ""
    graphics_strategy: str = ""
    broll_strategy: str = ""
    typography_strategy: str = ""
    transition_strategy: str = ""
    visual_priority_guidance: list[str] = Field(default_factory=list, max_length=12)
    style: dict[str, Any] = Field(default_factory=dict)
    beats: list[StoryBeat] = Field(default_factory=list, max_length=100)
    pacing_map: list[PacingWindow] = Field(default_factory=list, max_length=100)
    knowledge_refs: list[str] = Field(default_factory=list, max_length=20)


class AudioWordSignal(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    text: str = ""
    emphasis_score: float = Field(default=0, ge=0, le=1)
    energy: float = Field(default=0.5, ge=0, le=1)


class AudioWindow(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    words_per_second: float = Field(default=0, ge=0)
    speech_rate: Literal["slow", "medium", "fast"] = "medium"
    relative_loudness: float = Field(default=0.5, ge=0, le=1)
    energy: float = Field(default=0.5, ge=0, le=1)


class PauseSignal(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    duration: float = Field(gt=0)
    kind: Literal["micro", "short", "medium", "long"]


class AudioIntelligence(BaseModel):
    duration: float = Field(default=0, ge=0)
    windows: list[AudioWindow] = Field(default_factory=list, max_length=100)
    pauses: list[PauseSignal] = Field(default_factory=list, max_length=200)
    emphasis: list[AudioWordSignal] = Field(default_factory=list, max_length=300)
    sentence_boundaries: list[dict[str, Any]] = Field(default_factory=list, max_length=200)
    phrase_boundaries: list[dict[str, Any]] = Field(default_factory=list, max_length=300)
    source: Literal["voiceover_metadata", "wav_measurement", "mixed"] = "voiceover_metadata"


class VisualIntent(BaseModel):
    purpose: Literal["explain", "emphasize", "pace", "emotion", "continuity", "retain", "interest"]
    reason: str = Field(min_length=3, max_length=500)
    importance: float = Field(default=0.5, ge=0, le=1)


class CandidateDecision(BaseModel):
    selected: str | None = None
    alternatives: list[str] = Field(default_factory=list, max_length=5)
    reason: str = Field(default="", max_length=500)


class CriticProblem(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    start: float = Field(default=0, ge=0)
    end: float = Field(default=0, ge=0)
    severity: Literal["info", "low", "medium", "high", "severe"] = "medium"
    kind: str
    description: str = Field(max_length=1000)
    hard: bool = False
    suggested_action: str | None = Field(default=None, max_length=500)


class CriticReport(BaseModel):
    role: Literal["visual", "story", "continuity", "pacing", "technical"]
    score: float = Field(default=0, ge=0, le=10)
    problems: list[CriticProblem] = Field(default_factory=list, max_length=50)
    signals: dict[str, Any] = Field(default_factory=dict)


class AggregatedReview(BaseModel):
    overall_score: float = Field(default=0, ge=0, le=10)
    hard_failures: list[CriticProblem] = Field(default_factory=list, max_length=100)
    critical_problems: list[CriticProblem] = Field(default_factory=list, max_length=100)
    reports: list[CriticReport] = Field(default_factory=list, max_length=5)
    quality_changes: dict[str, float] = Field(default_factory=dict)
    early_exit: bool = False


class DirectorDecision(BaseModel):
    problem_id: str
    decision: Literal["accept", "reject", "modify"]
    reason: str = Field(max_length=500)


class DirectorReview(BaseModel):
    decisions: list[DirectorDecision] = Field(default_factory=list, max_length=50)
    rationale: str = Field(default="", max_length=1000)
    self_review: dict[str, Any] = Field(default_factory=dict)


class CorrectionRange(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    goal: str = Field(min_length=2, max_length=500)
    preserve: list[str] = Field(default_factory=list, max_length=20)


class CorrectionPlan(BaseModel):
    ranges: list[CorrectionRange] = Field(default_factory=list, max_length=10)
    actions: list[dict[str, Any]] = Field(default_factory=list, max_length=30)
    rationale: str = Field(default="", max_length=1000)


class NaturalLanguageEdit(BaseModel):
    scope_start: float | None = Field(default=None, ge=0)
    scope_end: float | None = Field(default=None, gt=0)
    intent: str = Field(default="", max_length=200)
    constraints: list[str] = Field(default_factory=list, max_length=20)
    preserve: list[str] = Field(default_factory=list, max_length=20)
    ambiguous: bool = False
    rationale: str = Field(default="", max_length=500)


class VariantRequest(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    goal: str = Field(min_length=2, max_length=500)
    count: int = Field(default=2, ge=2, le=3)


class RevisionDiff(BaseModel):
    from_revision: uuid.UUID
    to_revision: uuid.UUID
    changed_ranges: list[tuple[float, float]] = Field(default_factory=list, max_length=50)
    added_items: list[str] = Field(default_factory=list, max_length=100)
    removed_items: list[str] = Field(default_factory=list, max_length=100)
    quality_changes: dict[str, float] = Field(default_factory=dict)


class ModelCapabilityProfile(BaseModel):
    supports_tools: bool = False
    supports_vision: bool = False
    supports_video: bool = False
    supports_json_schema: bool = True
    max_context: int = Field(default=8192, ge=512)
