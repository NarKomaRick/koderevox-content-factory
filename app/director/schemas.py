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
    error: str | None
