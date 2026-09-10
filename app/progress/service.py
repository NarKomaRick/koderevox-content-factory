from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContentItem, JobProgress, ProgressEvent
from app.operations.clock import Clock, SystemClock
from app.operations.domain import ContentItemStatus
from app.progress.eta import ProgressETAEstimator
from app.progress.stages import JOB_STAGE_ORDERS, PIPELINE_STAGES, label_for


class JobProgressRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    job_type: str
    job_id: str
    state: str
    stage: str
    stage_label: str
    step_index: int | None
    step_total: int | None
    stage_progress: float | None
    message: str
    started_at: datetime | None
    updated_at: datetime
    completed_at: datetime | None
    estimated_remaining_seconds: float | None
    eta_confidence: str
    retry_count: int
    source_kind: str
    overall_progress: float | None = None


class ProgressReporter:
    """One throttled reporter used by Producer, Director, render and publish adapters."""

    def __init__(
        self,
        session: AsyncSession,
        job_type: str,
        job_id: uuid.UUID | str,
        *,
        clock: Clock | None = None,
        source_kind: str = "production",
        content_item_id: uuid.UUID | None = None,
        producer_run_id: uuid.UUID | None = None,
        director_run_id: uuid.UUID | None = None,
        production_project_id: uuid.UUID | None = None,
        min_delta: float = 0.03,
        min_interval_seconds: int = 20,
    ) -> None:
        self.session = session
        self.job_type = job_type
        self.job_id = str(job_id)
        self.clock = clock or SystemClock()
        self.source_kind = source_kind
        self.content_item_id = content_item_id
        self.producer_run_id = producer_run_id
        self.director_run_id = director_run_id
        self.production_project_id = production_project_id
        self.min_delta = min_delta
        self.min_interval_seconds = min_interval_seconds

    async def report_stage(
        self,
        stage: str,
        *,
        state: str = "running",
        progress: float | None = None,
        step_index: int | None = None,
        step_total: int | None = None,
        message: str = "",
        force: bool = False,
    ) -> JobProgress:
        now = self.clock.now()
        progress = None if progress is None else min(1.0, max(0.0, progress))
        row = await self._row()
        previous_stage = row.stage
        changed_stage = row.stage != stage
        meaningful = force or changed_stage or self._meaningful(row, progress, now)
        row.state = state
        row.stage = stage
        row.stage_label = label_for(stage)
        row.step_index = step_index
        row.step_total = step_total
        row.stage_progress = progress
        row.message = message[:2000]
        row.updated_at = now
        if row.started_at is None:
            row.started_at = now
        if self.source_kind:
            row.source_kind = self.source_kind
        if meaningful:
            if changed_stage and previous_stage != "created":
                if state == "waiting":
                    await self._pause_previous(row)
                else:
                    await self._close_previous(row, now)
            self.session.add(
                ProgressEvent(
                    progress_id=row.id,
                    event_type="stage_started" if changed_stage else "update",
                    stage=stage,
                    stage_progress=progress,
                    message=message[:2000],
                    source_kind=self.source_kind,
                    occurred_at=now,
                )
            )
        await self.session.commit()
        return row

    async def complete(self, *, message: str = "Готово") -> JobProgress:
        row = await self._row()
        now = self.clock.now()
        row.state = "completed"
        row.stage_progress = 1.0
        row.message = message
        row.updated_at = now
        row.completed_at = now
        await self._close_previous(row, now)
        await self.session.commit()
        return row

    async def waiting(self, stage: str, *, message: str, reason: str = "approval") -> JobProgress:
        return await self.report_stage(stage, state="waiting", message=message, force=True)

    async def fail(self, *, error_code: str, message: str, retry_count: int = 0) -> JobProgress:
        row = await self._row()
        row.state = "retrying" if retry_count else "failed"
        row.error_code = error_code
        row.retry_count = retry_count
        row.message = message[:2000]
        row.updated_at = self.clock.now()
        self.session.add(
            ProgressEvent(
                progress_id=row.id,
                event_type="failed",
                stage=row.stage,
                stage_progress=row.stage_progress,
                message=message[:2000],
                source_kind=self.source_kind,
                occurred_at=self.clock.now(),
            )
        )
        await self.session.commit()
        return row

    async def _row(self) -> JobProgress:
        row = await self.session.scalar(
            select(JobProgress).where(
                JobProgress.job_type == self.job_type, JobProgress.job_id == self.job_id
            )
        )
        if row is None:
            row = JobProgress(
                job_type=self.job_type,
                job_id=self.job_id,
                content_item_id=self.content_item_id,
                producer_run_id=self.producer_run_id,
                director_run_id=self.director_run_id,
                production_project_id=self.production_project_id,
                source_kind=self.source_kind,
                started_at=self.clock.now(),
            )
            self.session.add(row)
            await self.session.flush()
        return row

    async def _close_previous(self, row: JobProgress, now: datetime) -> None:
        previous = await self.session.scalar(
            select(ProgressEvent)
            .where(
                ProgressEvent.progress_id == row.id,
                ProgressEvent.event_type.in_(["stage_started", "update"]),
            )
            .order_by(ProgressEvent.occurred_at.desc())
        )
        if previous is not None and previous.duration_seconds is None:
            previous.duration_seconds = self._elapsed(now, previous.occurred_at)
            previous.event_type = "stage_completed"

    async def _pause_previous(self, row: JobProgress) -> None:
        previous = await self.session.scalar(
            select(ProgressEvent)
            .where(
                ProgressEvent.progress_id == row.id,
                ProgressEvent.event_type.in_(["stage_started", "update"]),
            )
            .order_by(ProgressEvent.occurred_at.desc())
        )
        if previous is not None:
            previous.event_type = "stage_paused"

    def _meaningful(self, row: JobProgress, progress: float | None, now: datetime) -> bool:
        if progress is not None and row.stage_progress is not None:
            if abs(progress - row.stage_progress) >= self.min_delta:
                return True
        return self._elapsed(now, row.updated_at) >= self.min_interval_seconds

    @staticmethod
    def _elapsed(now: datetime, earlier: datetime) -> float:
        if earlier.tzinfo is None:
            earlier = earlier.replace(tzinfo=UTC)
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        return max(0.0, (now - earlier).total_seconds())


class PipelineProgressService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def for_job(self, job_type: str, job_id: uuid.UUID | str) -> JobProgressRead | None:
        row = await self.session.scalar(
            select(JobProgress).where(
                JobProgress.job_type == job_type, JobProgress.job_id == str(job_id)
            )
        )
        if row is None:
            return None
        snapshot = JobProgressRead.model_validate(row)
        if row.state == "completed":
            snapshot.overall_progress = 1.0
        else:
            order = JOB_STAGE_ORDERS.get(job_type, ())
            index = order.index(row.stage) if row.stage in order else 0
            denominator = max(1, len(order) - 1)
            snapshot.overall_progress = round(
                min(1.0, max(0.0, (index + (row.stage_progress or 0.0)) / denominator)), 4
            )
        return snapshot

    async def attach_telegram_message(
        self, job_type: str, job_id: uuid.UUID | str, chat_id: int, message_id: int
    ) -> JobProgress:
        row = await self.session.scalar(
            select(JobProgress).where(
                JobProgress.job_type == job_type, JobProgress.job_id == str(job_id)
            )
        )
        if row is None:
            row = JobProgress(job_type=job_type, job_id=str(job_id), source_kind="production")
            self.session.add(row)
            await self.session.flush()
        row.telegram_chat_id = chat_id
        row.telegram_message_id = message_id
        await self.session.commit()
        return row

    async def for_item(self, content_item_id: uuid.UUID) -> dict[str, Any]:
        item = await self.session.get(ContentItem, content_item_id)
        if item is None:
            raise ValueError("ContentItem not found")
        rows = (
            await self.session.scalars(
                select(JobProgress)
                .where(JobProgress.content_item_id == content_item_id)
                .order_by(JobProgress.updated_at.desc())
            )
        ).all()
        by_type = {row.job_type: row for row in rows}
        active_keys = _expected_stage_keys(item, by_type)
        active = [definition for definition in PIPELINE_STAGES if definition.key in active_keys]
        if not active:
            active = [PIPELINE_STAGES[0]]
        total_weight = sum(stage.weight for stage in active)
        overall = 0.0
        for stage in active:
            row = by_type.get(stage.key)
            value = (
                1.0
                if row and row.state == "completed"
                else (row.stage_progress or 0.0 if row else 0.0)
            )
            overall += stage.weight * value
        overall /= total_weight or 1.0
        current = next(
            (row for row in rows if row.state in {"running", "retrying", "waiting"}),
            rows[0] if rows else None,
        )
        waiting_for_approval = item.status in {
            ContentItemStatus.AWAITING_SCRIPT_APPROVAL,
            ContentItemStatus.AWAITING_PREVIEW_APPROVAL,
        }
        eta = await ProgressETAEstimator(self.session).estimate(
            [stage.key for stage in active],
            source_kind=current.source_kind if current else "production",
        )
        return {
            "content_item_id": str(content_item_id),
            "overall_progress": round(min(1.0, max(0.0, overall)), 4),
            "current": JobProgressRead.model_validate(current).model_dump(mode="json")
            if current
            else None,
            "stages": [JobProgressRead.model_validate(row).model_dump(mode="json") for row in rows],
            "estimated_remaining_seconds": eta.seconds
            if current and current.state != "waiting" and not waiting_for_approval
            else None,
            "eta_confidence": (
                "none"
                if waiting_for_approval or (current and current.state == "waiting")
                else eta.confidence
            ),
            "status": item.status,
        }


def _expected_stage_keys(item: ContentItem, existing: dict[str, JobProgress]) -> set[str]:
    """Keep future stages in the denominator once a pipeline has committed to them."""
    status = ContentItemStatus(item.status)
    keys = set(existing)
    if status in {
        ContentItemStatus.PLANNED,
        ContentItemStatus.QUEUED,
        ContentItemStatus.DEFERRED,
        ContentItemStatus.PAUSED,
        ContentItemStatus.PRODUCER_RUNNING,
        ContentItemStatus.FAILED,
        ContentItemStatus.MANUAL_REQUIRED,
    }:
        keys.add("producer")
    if item.production_project_id is not None or status in {
        ContentItemStatus.PRODUCER_READY,
        ContentItemStatus.AWAITING_SCRIPT_APPROVAL,
        ContentItemStatus.DIRECTOR_QUEUED,
        ContentItemStatus.DIRECTOR_RUNNING,
        ContentItemStatus.PREVIEW_READY,
        ContentItemStatus.AWAITING_PREVIEW_APPROVAL,
        ContentItemStatus.APPROVED,
        ContentItemStatus.READY_TO_PUBLISH,
        ContentItemStatus.PUBLISHING,
        ContentItemStatus.PUBLISHED,
    }:
        keys.update({"producer", "director", "render"})
    if status in {
        ContentItemStatus.READY_TO_PUBLISH,
        ContentItemStatus.PUBLISHING,
        ContentItemStatus.PUBLISHED,
    }:
        keys.add("publish")
    return keys
