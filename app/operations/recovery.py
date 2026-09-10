from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import ContentItem, JobProgress
from app.operations.audit import audit
from app.operations.clock import Clock, SystemClock
from app.operations.domain import ContentItemStatus, ensure_content_item_transition
from app.operations.policies import OperationsPolicy


class RecoveryManager:
    def __init__(
        self, session: AsyncSession, settings: Settings | None = None, *, clock: Clock | None = None
    ) -> None:
        self.session = session
        self.settings = settings or Settings()
        self.clock = clock or SystemClock()
        self.policy = OperationsPolicy.from_settings(self.settings)

    async def recover_stale(self) -> list[uuid.UUID]:
        now = self.clock.now()
        statuses = [
            ContentItemStatus.PRODUCER_RUNNING,
            ContentItemStatus.DIRECTOR_RUNNING,
        ]
        rows = (
            await self.session.scalars(
                select(ContentItem).where(
                    ContentItem.status.in_(statuses)
                )
            )
        ).all()
        recovered: list[uuid.UUID] = []
        for item in rows:
            heartbeat = await self.session.scalar(
                select(JobProgress.updated_at)
                .where(JobProgress.content_item_id == item.id)
                .order_by(JobProgress.updated_at.desc())
                .limit(1)
            )
            last_seen = self._as_aware(heartbeat or item.updated_at)
            timeout_seconds = (
                self.settings.operations_director_stale_seconds
                if item.current_stage == "director"
                else self.settings.operations_producer_stale_seconds
            )
            if last_seen >= now - timedelta(seconds=timeout_seconds):
                continue
            target_status = (
                ContentItemStatus.QUEUED
                if item.retry_count < self.policy.max_producer_retries
                else ContentItemStatus.MANUAL_REQUIRED
            )
            ensure_content_item_transition(item.status, target_status)
            item.status = target_status
            item.blocked_reason = None
            item.failure_report = {
                **item.failure_report,
                "recovery": "stale_job_detected",
                "recovered_at": now.isoformat(),
            }
            await audit(
                self.session,
                "recovery_performed",
                strategy_id=item.strategy_id,
                project_id=item.project_id,
                content_item_id=item.id,
                rationale="heartbeat timeout",
                data={"new_status": item.status},
            )
            recovered.append(item.id)
        await self.session.commit()
        return recovered

    @staticmethod
    def _as_aware(value: datetime) -> datetime:
        return value.replace(tzinfo=UTC) if value.tzinfo is None else value
