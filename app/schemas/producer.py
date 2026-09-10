from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.producer.domain import ApprovalState, ProducerStatus, ResearchMode


class ProducerRunCreate(BaseModel):
    prompt: str = Field(min_length=1, max_length=20_000)
    project_id: uuid.UUID | None = None
    user_id: uuid.UUID | None = None
    telegram_user_id: int | None = None
    platform: str = Field(default="youtube_shorts", max_length=64)
    duration: float | None = Field(default=None, ge=5, le=3600)
    tone: str | None = Field(default=None, max_length=255)
    research_mode: ResearchMode = ResearchMode.FIXTURES
    approval_mode: bool = False
    idempotency_key: str | None = Field(default=None, max_length=255)

    @model_validator(mode="after")
    def has_owner_hint(self) -> ProducerRunCreate:
        if self.user_id is None and self.telegram_user_id is None:
            raise ValueError("user_id or telegram_user_id is required")
        return self


class ProducerRunRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    user_id: uuid.UUID
    raw_prompt: str
    platform: str
    target_duration: float | None
    tone: str | None
    research_mode: str
    approval_mode: bool
    approval_state: ApprovalState
    status: ProducerStatus
    current_stage: ProducerStatus
    idempotency_key: str | None
    step_count: int
    llm_call_count: int
    search_query_count: int
    source_count: int
    fetch_count: int
    script_iterations: int
    artifacts: dict[str, Any]
    errors: list[dict[str, Any]]
    error: str | None
    production_project_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None
    cancelled_at: datetime | None
