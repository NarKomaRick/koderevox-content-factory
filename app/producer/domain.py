from __future__ import annotations

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ProducerStatus(StrEnum):
    CREATED = "created"
    UNDERSTANDING_GOAL = "understanding_goal"
    RESEARCHING = "researching"
    VERIFYING = "verifying"
    PLANNING_ANGLE = "planning_angle"
    BUILDING_BRIEF = "building_brief"
    WRITING_SCRIPT = "writing_script"
    REVIEWING_SCRIPT = "reviewing_script"
    PLANNING_ASSETS = "planning_assets"
    CREATING_PRODUCTION = "creating_production"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ApprovalState(StrEnum):
    NOT_REQUIRED = "not_required"
    PENDING = "pending"
    APPROVED = "approved"


class ResearchMode(StrEnum):
    NONE = "none"
    FIXTURES = "fixtures"
    CONTROLLED = "controlled"


class ProducerIntent(BaseModel):
    raw_prompt: str = Field(min_length=1, max_length=20_000)
    topic: str | None = Field(default=None, max_length=1000)
    audience: str = ""
    platform: str = "youtube_shorts"
    target_duration: float = Field(default=45, ge=5, le=3600)
    tone: str = "clear, useful, conversational"
    research_mode: ResearchMode = ResearchMode.FIXTURES
    approval_mode: bool = False
    language: str = "ru"
    explicit_topic: bool = False
    cta: str = ""


class TopicCandidate(BaseModel):
    title: str
    core_message: str
    rationale: str = ""
    score: float = Field(default=0.0, ge=0, le=1)


class ResearchPlan(BaseModel):
    queries: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    reason: str = ""


class ResearchFact(BaseModel):
    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    claim: str = Field(min_length=2, max_length=5000)
    normalized_claim: str = ""
    confidence: float = Field(default=0.8, ge=0, le=1)
    source_ids: list[uuid.UUID] = Field(default_factory=list)
    verified: bool = False
    critical: bool = False
    time_sensitive: bool = False
    stale: bool = False
    conflict_group: str | None = None


class FactConflict(BaseModel):
    fact_ids: list[uuid.UUID]
    claims: list[str]
    critical: bool = False
    resolution: str | None = None


class ContentAngle(BaseModel):
    title: str
    promise: str
    hook: str
    core_message: str
    score: float = Field(default=0.0, ge=0, le=1)
    duplicate: bool = False
    duplicate_reason: str | None = None


class ContentBrief(BaseModel):
    title: str
    audience: str
    promise: str
    hook: str
    core_message: str
    tone: str
    platform: str
    target_duration: float = Field(gt=0)
    cta: str = ""
    structure: list[str] = Field(default_factory=list)
    fact_ids: list[uuid.UUID] = Field(default_factory=list)


class ScriptSegment(BaseModel):
    id: str
    purpose: str
    text: str
    start_second: float = Field(default=0, ge=0)
    end_second: float = Field(default=1, gt=0)
    factual: bool = False
    fact_ids: list[uuid.UUID] = Field(default_factory=list)

    @model_validator(mode="after")
    def valid_range(self) -> ScriptSegment:
        if self.end_second <= self.start_second:
            raise ValueError("script segment end must be greater than start")
        if self.factual and not self.fact_ids:
            raise ValueError("factual script segment must bind at least one fact")
        return self


class ScriptOutline(BaseModel):
    content: str
    segments: list[ScriptSegment] = Field(min_length=1)
    estimated_duration: float = Field(gt=0)
    revision: int = 0


class ScriptReview(BaseModel):
    passed: bool
    issues: list[str] = Field(default_factory=list)
    unsupported_claims: list[str] = Field(default_factory=list)
    conflicting_claims: list[str] = Field(default_factory=list)
    spoken_language_score: float = Field(default=1.0, ge=0, le=1)
    duration_seconds: float = Field(default=0, ge=0)
    suggested_revision: str | None = None


class AssetRequirement(BaseModel):
    id: str
    description: str
    semantic_role: str = "illustrative"
    source_hint: str | None = None
    must_be_actual: bool = False
    safe_alternative: str | None = None


class AssetPlan(BaseModel):
    requirements: list[AssetRequirement] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class DirectorHandoffPackage(BaseModel):
    brief: ContentBrief
    final_script: ScriptOutline
    verified_facts: list[ResearchFact]
    story_intent: dict[str, Any]
    asset_plan: AssetPlan
    brand_profile: dict[str, Any] = Field(default_factory=dict)
    channel_profile: dict[str, Any] = Field(default_factory=dict)
    output_profile: dict[str, Any] = Field(default_factory=dict)
    source_references: list[dict[str, Any]] = Field(default_factory=list)


class ProducerReport(BaseModel):
    run_id: uuid.UUID
    status: ProducerStatus
    current_stage: ProducerStatus
    approval_state: ApprovalState
    topic: str | None = None
    facts: list[ResearchFact] = Field(default_factory=list)
    conflicts: list[FactConflict] = Field(default_factory=list)
    brief: ContentBrief | None = None
    script: ScriptOutline | None = None
    review: ScriptReview | None = None
    asset_plan: AssetPlan | None = None
    handoff: DirectorHandoffPackage | None = None
    production_project_id: uuid.UUID | None = None
    error: str | None = None
    created_at: datetime | None = None
    completed_at: datetime | None = None


class ProducerORMRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
