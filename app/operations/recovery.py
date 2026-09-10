from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import ContentItem
from app.operations.audit import audit
from app.operations.clock import Clock, SystemClock
from app.operations.domain import ContentItemStatus
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
        timeout = timedelta(seconds=self.settings.operations_producer_stale_seconds)
        statuses = [
            ContentItemStatus.PRODUCER_RUNNING,
            ContentItemStatus.DIRECTOR_RUNNING,
            ContentItemStatus.PREVIEW_READY,
        ]
        rows = (
            await self.session.scalars(
                select(ContentItem).where(
                    ContentItem.status.in_(statuses), ContentItem.updated_at < now - timeout
                )
            )
        ).all()
        recovered: list[uuid.UUID] = []
        for item in rows:
            item.status = (
                ContentItemStatus.QUEUED
                if item.retry_count < self.policy.max_producer_retries
                else ContentItemStatus.MANUAL_REQUIRED
            )
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
