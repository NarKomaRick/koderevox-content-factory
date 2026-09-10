from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import ContentItem, ContentStrategy, JobProgress
from app.operations.clock import Clock, SystemClock
from app.operations.domain import ContentItemStatus
from app.operations.execution import ExecutionCoordinator
from app.operations.locking import OperationsTickLock
from app.operations.planner import ContentPlanner
from app.operations.policies import OperationsPolicy
from app.operations.recovery import RecoveryManager
from app.operations.schemas import OperationsStatus


class StudioOrchestrator:
    """One bounded, idempotent operations tick; no LLM controls transitions."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings | None = None,
        *,
        clock: Clock | None = None,
        fake: bool | None = None,
        actor_user_id: uuid.UUID | None = None,
    ) -> None:
        self.session = session
        self.settings = settings or Settings()
        self.clock = clock or SystemClock()
        self.policy = OperationsPolicy.from_settings(self.settings)
        self.fake = self.settings.operations_dry_run if fake is None else fake
        self.actor_user_id = actor_user_id

    async def run_once(self, *, strategy_id: uuid.UUID | None = None) -> dict[str, Any]:
        if not self.policy.enabled and not self.fake:
            return {"enabled": False, "planned": 0, "executed": 0, "recovered": 0}
        async with OperationsTickLock(self.session) as acquired:
            if not acquired:
                return {
                    "enabled": True,
                    "planned": 0,
                    "executed": 0,
                    "recovered": 0,
                    "locked": True,
                }
            return await self._run_once_unlocked(strategy_id=strategy_id)

    async def _run_once_unlocked(self, *, strategy_id: uuid.UUID | None) -> dict[str, Any]:
        recovered = await RecoveryManager(
            self.session, self.settings, clock=self.clock
        ).recover_stale()
        strategies_query = select(ContentStrategy).where(
            ContentStrategy.enabled.is_(True), ContentStrategy.paused.is_(False)
        )
        if strategy_id:
            strategies_query = strategies_query.where(ContentStrategy.id == strategy_id)
        if self.actor_user_id is not None:
            strategies_query = strategies_query.where(ContentStrategy.user_id == self.actor_user_id)
        strategies = (await self.session.scalars(strategies_query)).all()
        planned = 0
        for strategy in strategies:
            result = await ContentPlanner(
                self.session, clock=self.clock, policy=self.policy
            ).plan_strategy(strategy.id)
            planned += len(result.items_to_create)
        runnable = (
            await self.session.scalars(
                select(ContentItem)
                .where(
                    *([ContentItem.user_id == self.actor_user_id] if self.actor_user_id else []),
                    ContentItem.status.in_(
                        [
                            ContentItemStatus.PLANNED,
                            ContentItemStatus.QUEUED,
                            ContentItemStatus.DEFERRED,
                            ContentItemStatus.DIRECTOR_QUEUED,
                        ]
                    ),
                    or_(
                        ContentItem.scheduled_for.is_(None),
                        ContentItem.scheduled_for <= self.clock.now(),
                    ),
                    or_(
                        ContentItem.next_retry_at.is_(None),
                        ContentItem.next_retry_at <= self.clock.now(),
                    ),
                )
                .order_by(ContentItem.priority.desc(), ContentItem.scheduled_for)
                .limit(self.policy.max_active_items)
            )
        ).all()
        executed = 0
        coordinator = ExecutionCoordinator(self.session, self.settings, fake=self.fake)
        for item in runnable:
            if await self._dependencies_blocked(item.id):
                item.blocked_reason = "dependency"
                await self.session.commit()
                continue
            await coordinator.execute(item.id)
            executed += 1
        return {
            "enabled": True,
            "planned": planned,
            "executed": executed,
            "recovered": len(recovered),
        }

    async def _dependencies_blocked(self, item_id: uuid.UUID) -> bool:
        from app.models import ContentDependency

        deps = (
            await self.session.scalars(
                select(ContentDependency).where(ContentDependency.content_item_id == item_id)
            )
        ).all()
        for dependency in deps:
            required = await self.session.get(ContentItem, dependency.depends_on_item_id)
            if required is None:
                dependency.status = "failed"
                return True
            if required.status not in {
                ContentItemStatus.PUBLISHED,
                ContentItemStatus.APPROVED,
                ContentItemStatus.READY_TO_PUBLISH,
            }:
                dependency.status = "pending"
                return True
            dependency.status = "satisfied"
        return False

    async def status(self) -> OperationsStatus:
        counts: dict[str, int] = {}
        rows = (
            await self.session.execute(
                select(ContentItem.status, func.count())
                .where(
                    *([ContentItem.user_id == self.actor_user_id] if self.actor_user_id else [])
                )
                .group_by(ContentItem.status)
            )
        ).all()
        counts.update({str(status): int(count) for status, count in rows})
        week = self.clock.now() - timedelta(days=7)
        published = int(
            await self.session.scalar(
                select(func.count())
                .select_from(ContentItem)
                .where(
                    ContentItem.status == ContentItemStatus.PUBLISHED,
                    ContentItem.completed_at >= week,
                    *([ContentItem.user_id == self.actor_user_id] if self.actor_user_id else []),
                )
            )
            or 0
        )
        strategies = int(
            await self.session.scalar(
                select(func.count())
                .select_from(ContentStrategy)
                .where(ContentStrategy.enabled.is_(True))
                .where(
                    *([ContentStrategy.user_id == self.actor_user_id] if self.actor_user_id else [])
                )
            )
            or 0
        )
        progress_query = select(JobProgress).where(
            JobProgress.state.in_(["running", "retrying", "waiting"])
        )
        if self.actor_user_id is not None:
            progress_query = progress_query.join(
                ContentItem, JobProgress.content_item_id == ContentItem.id
            ).where(ContentItem.user_id == self.actor_user_id)
        active_progress = (await self.session.scalars(progress_query)).all()
        approvals = counts.get(ContentItemStatus.AWAITING_SCRIPT_APPROVAL, 0) + counts.get(
            ContentItemStatus.AWAITING_PREVIEW_APPROVAL, 0
        )
        return OperationsStatus(
            strategies=strategies,
            planned=counts.get(ContentItemStatus.PLANNED, 0),
            queued=counts.get(ContentItemStatus.QUEUED, 0),
            producer_running=counts.get(ContentItemStatus.PRODUCER_RUNNING, 0),
            director_running=counts.get(ContentItemStatus.DIRECTOR_RUNNING, 0),
            ready_to_publish=counts.get(ContentItemStatus.READY_TO_PUBLISH, 0),
            awaiting_approval=approvals,
            failed=counts.get(ContentItemStatus.FAILED, 0)
            + counts.get(ContentItemStatus.MANUAL_REQUIRED, 0),
            published_this_week=published,
            blocked_items=sum(counts.get(status, 0) for status in (ContentItemStatus.DEFERRED,)),
            stale_runs=0,
            active_jobs=[
                {
                    "job_type": row.job_type,
                    "job_id": row.job_id,
                    "stage": row.stage,
                    "stage_label": row.stage_label,
                    "progress": row.stage_progress,
                    "state": row.state,
                    "updated_at": row.updated_at,
                }
                for row in active_progress
            ],
        )
