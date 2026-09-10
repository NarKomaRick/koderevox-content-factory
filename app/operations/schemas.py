from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.operations.domain import (
    ApprovalCheckpoint,
    ApprovalPolicy,
    ContentItemStatus,
    ManualPriority,
)


class PillarInput(BaseModel):
    name: str = Field(min_length=1, max_length=128)
    weight: float = Field(default=0.25, ge=0, le=1)
    enabled: bool = True
    minimum_gap_days: int = Field(default=0, ge=0, le=365)


class StrategyCreate(BaseModel):
    project_id: uuid.UUID
    user_id: uuid.UUID
    channel_profile_id: uuid.UUID | None = None
    name: str = Field(min_length=2, max_length=255)
    goal: str = ""
    content_pillars: list[PillarInput] = Field(min_length=1)
    default_platforms: list[str] = Field(default_factory=lambda: ["youtube_shorts"])
    default_duration: float = Field(default=60, ge=5, le=3600)
    weekly_target: int = Field(default=3, ge=1, le=100)
    approval_policy: ApprovalPolicy = ApprovalPolicy.BEFORE_PUBLISH
    autonomous_mode: bool = True
    auto_publish: bool = False
    timezone: str = "Europe/Moscow"
    recurrence_rule: dict[str, Any] = Field(default_factory=dict)
    budget: dict[str, Any] = Field(default_factory=dict)


class StrategyPatch(BaseModel):
    name: str | None = Field(default=None, min_length=2, max_length=255)
    goal: str | None = None
    weekly_target: int | None = Field(default=None, ge=1, le=100)
    approval_policy: ApprovalPolicy | None = None
    enabled: bool | None = None
    paused: bool | None = None
    autonomous_mode: bool | None = None
    auto_publish: bool | None = None
    recurrence_rule: dict[str, Any] | None = None
    budget: dict[str, Any] | None = None


class StrategyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    name: str
    goal: str
    default_platforms: list[str]
    default_duration: float
    weekly_target: int
    approval_policy: ApprovalPolicy
    autonomous_mode: bool
    auto_publish: bool
    enabled: bool
    paused: bool
    timezone: str
    recurrence_rule: dict[str, Any]
    budget: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class CampaignCreate(BaseModel):
    strategy_id: uuid.UUID
    name: str = Field(min_length=2, max_length=255)
    goal: str = ""
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    priority: int = Field(default=50, ge=0, le=100)
    target_content_count: int | None = Field(default=None, ge=1, le=1000)
    allowed_pillars: list[str] = Field(default_factory=list)
    instructions: list[str] = Field(default_factory=list)


class SeriesCreate(BaseModel):
    strategy_id: uuid.UUID
    name: str = Field(min_length=2, max_length=255)
    description: str = ""
    sequence_mode: str = "ordered"


class ContentItemCreate(BaseModel):
    strategy_id: uuid.UUID
    topic_hint: str | None = None
    title_hint: str | None = None
    pillar: str | None = None
    scheduled_for: datetime | None = None
    priority: int = Field(default=50, ge=0, le=100)
    manual_priority: ManualPriority = ManualPriority.NORMAL
    target_platforms: list[str] | None = None
    campaign_id: uuid.UUID | None = None
    series_id: uuid.UUID | None = None
    series_position: int | None = Field(default=None, ge=1)
    locked: bool = False
    idempotency_key: str | None = None


class ContentItemPatch(BaseModel):
    topic_hint: str | None = None
    title_hint: str | None = None
    scheduled_for: datetime | None = None
    priority: int | None = Field(default=None, ge=0, le=100)
    manual_priority: ManualPriority | None = None
    locked: bool | None = None
    lock_reason: str | None = None
    pillar: str | None = None


class ContentItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    strategy_id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    campaign_id: uuid.UUID | None
    series_id: uuid.UUID | None
    series_position: int | None
    title_hint: str | None
    topic_hint: str | None
    pillar: str | None
    status: ContentItemStatus
    priority: int
    manual_priority: ManualPriority
    scheduled_for: datetime | None
    publish_not_before: datetime | None
    publish_before: datetime | None
    target_platforms: list[str]
    producer_run_id: uuid.UUID | None
    production_project_id: uuid.UUID | None
    approval_state: str
    blocked_reason: str | None
    operator_notes: list[str]
    locked: bool
    lock_reason: str | None
    attempts: int
    retry_count: int
    current_stage: str | None
    failure_report: dict[str, Any]
    resource_estimate: dict[str, Any]
    idempotency_key: str
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None


class ApprovalRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    content_item_id: uuid.UUID
    checkpoint: ApprovalCheckpoint
    status: str
    requested_at: datetime
    responded_at: datetime | None
    comment: str | None


class ApprovalDecision(BaseModel):
    comment: str | None = Field(default=None, max_length=4000)
    actor_user_id: uuid.UUID | None = None


class PlannerResult(BaseModel):
    items_to_create: list[ContentItemRead] = Field(default_factory=list)
    items_to_reschedule: list[uuid.UUID] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class OperationsStatus(BaseModel):
    strategies: int
    planned: int
    queued: int
    producer_running: int
    director_running: int
    ready_to_publish: int
    awaiting_approval: int
    failed: int
    published_this_week: int
    blocked_items: int
    stale_runs: int
    active_jobs: list[dict[str, Any]] = Field(default_factory=list)


class CalendarEntry(BaseModel):
    date: datetime | None
    item: ContentItemRead


class PipelineSnapshot(BaseModel):
    content_item: ContentItemRead
    producer: str
    director: str
    render: str
    approval: str
    publish: str
