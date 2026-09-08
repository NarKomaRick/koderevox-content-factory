import uuid
from typing import Any

from pydantic import BaseModel, Field, model_validator

from app.models.enums import VisualLayout, VisualTransition


class VisualInsertion(BaseModel):
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    asset_id: uuid.UUID
    role: str = Field(default="illustration", min_length=1, max_length=64)
    layout: VisualLayout = VisualLayout.FULLSCREEN
    reason: str = Field(default="", max_length=500)
    transition: VisualTransition = VisualTransition.FADE
    required: bool = False
    settings: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_range(self) -> "VisualInsertion":
        if self.end <= self.start:
            raise ValueError("visual insertion end must be greater than start")
        return self


class VisualPlan(BaseModel):
    insertions: list[VisualInsertion] = Field(default_factory=list, max_length=100)
    reasoning_summary: str = Field(default="", max_length=2000)


class VisualPlanPatch(BaseModel):
    visual_plan: VisualPlan


class VisualSuggestionRequest(BaseModel):
    instruction: str | None = Field(default=None, max_length=2000)


class VisualInstructionRequest(BaseModel):
    instruction: str = Field(min_length=2, max_length=2000)


class ManualVisualInsertion(BaseModel):
    insertion: VisualInsertion


class VisualSuggestion(BaseModel):
    insertion: VisualInsertion
    asset: dict[str, Any]


class AssetRecommendation(BaseModel):
    asset_id: uuid.UUID
    start: float = Field(ge=0)
    end: float = Field(gt=0)
    role: str = Field(default="illustration", max_length=64)
    layout: VisualLayout
    reason: str = Field(min_length=3, max_length=500)


class AssetRecommendationBatch(BaseModel):
    recommendations: list[AssetRecommendation] = Field(default_factory=list, max_length=10)
    reasoning_summary: str = Field(default="", max_length=1000)
