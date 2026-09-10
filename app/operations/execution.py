from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import ContentItem, ContentStrategy
from app.operations.approvals import ApprovalManager
from app.operations.audit import audit
from app.operations.budgets import BudgetManager
from app.operations.capacity import CapacityManager
from app.operations.domain import ApprovalCheckpoint, ContentItemStatus, ErrorClass
from app.operations.policies import OperationsPolicy
from app.producer.runtime import ProducerRuntime, ProducerService
from app.schemas.producer import ProducerRunCreate


class ExecutionCoordinator:
    """Coordinates existing phase runtimes; it owns operational transitions only."""

    def __init__(
        self, session: AsyncSession, settings: Settings | None = None, *, fake: bool | None = None
    ) -> None:
        self.session = session
        self.settings = settings or Settings()
        self.policy = OperationsPolicy.from_settings(self.settings)
        self.fake = self.policy.dry_run if fake is None else fake
        self.capacity = CapacityManager(session, self.settings)
        self.budgets = BudgetManager(session, self.settings)

    async def execute(self, item_id: uuid.UUID) -> ContentItem:
        item = await self.session.get(ContentItem, item_id)
        if item is None:
            raise ValueError("ContentItem not found")
        strategy = await self.session.get(ContentStrategy, item.strategy_id)
        if strategy is None:
            raise ValueError("ContentStrategy not found")
        if item.status in {
            ContentItemStatus.CANCELLED,
            ContentItemStatus.PUBLISHED,
            ContentItemStatus.MANUAL_REQUIRED,
            ContentItemStatus.PAUSED,
        }:
            return item
        if item.status in {ContentItemStatus.PLANNED, ContentItemStatus.DEFERRED}:
            item.status = ContentItemStatus.QUEUED
        if item.status == ContentItemStatus.QUEUED:
            budget = await self.budgets.check(strategy)
            if budget.decision != "allow":
                item.status = ContentItemStatus.DEFERRED
                item.blocked_reason = "budget"
                await audit(
                    self.session,
                    "budget_denied",
                    strategy_id=item.strategy_id,
                    project_id=item.project_id,
                    content_item_id=item.id,
                    rationale=budget.reason,
                )
                await self.session.commit()
                return item
            capacity = await self.capacity.check("producer")
            if not capacity.allowed:
                item.blocked_reason = "capacity"
                await audit(
                    self.session,
                    "capacity_denied",
                    strategy_id=item.strategy_id,
                    project_id=item.project_id,
                    content_item_id=item.id,
                    rationale=capacity.reason,
                )
                await self.session.commit()
                return item
            item.status = ContentItemStatus.PRODUCER_RUNNING
            item.current_stage = "producer"
            item.attempts += 1
            await audit(
                self.session,
                "producer_started",
                strategy_id=item.strategy_id,
                project_id=item.project_id,
                content_item_id=item.id,
                rationale="runnable item claimed",
            )
            await self.session.commit()
            if not self.fake:
                return item
            if item.topic_hint == "temporary-failure" and item.attempts == 1:
                return await self._failure(
                    item, ErrorClass.TEMPORARY, "simulated temporary provider failure"
                )
            run = await ProducerService(self.session, self.settings).create(
                ProducerRunCreate(
                    prompt=item.topic_hint or item.title_hint or "Создай полезный ролик",
                    project_id=item.project_id,
                    user_id=item.user_id,
                    platform=(strategy.default_platforms or ["youtube_shorts"])[0],
                    duration=strategy.default_duration,
                    approval_mode=False,
                    research_mode="fixtures",
                    idempotency_key=f"content-item:{item.id}:producer",
                )
            )
            item.producer_run_id = run.id
            if not self.fake:
                from app.tasks.queue import CeleryProducerTaskQueue

                CeleryProducerTaskQueue().enqueue(run.id)
                return item
            result = await ProducerRuntime(self.session, self.settings).run(run.id)
            if result.status != "completed":
                return await self._failure(
                    item,
                    ErrorClass.TEMPORARY
                    if result.status == "failed"
                    else ErrorClass.MANUAL_REQUIRED,
                    result.error or "Producer did not complete",
                )
            item.production_project_id = result.production_project_id
            item.status = ContentItemStatus.PRODUCER_READY
            await self.session.commit()
            if self.policy.requires_script_approval(strategy.approval_policy):
                await ApprovalManager(self.session, policy=self.policy).request(
                    item.id, ApprovalCheckpoint.SCRIPT
                )
                return item
        if item.status in {ContentItemStatus.PRODUCER_READY, ContentItemStatus.DIRECTOR_QUEUED}:
            item.status = ContentItemStatus.DIRECTOR_RUNNING
            item.current_stage = "director"
            await audit(
                self.session,
                "director_started",
                strategy_id=item.strategy_id,
                project_id=item.project_id,
                content_item_id=item.id,
                rationale="Producer handoff is ready",
            )
            await self.session.commit()
            if not self.fake:
                item.status = ContentItemStatus.DIRECTOR_QUEUED
                await self.session.commit()
                return item
            item.status = ContentItemStatus.PREVIEW_READY
            item.current_stage = "render"
            await audit(
                self.session,
                "render_enqueued",
                strategy_id=item.strategy_id,
                project_id=item.project_id,
                content_item_id=item.id,
                rationale="fake Director and renderer completed",
            )
            await self.session.commit()
        if item.status == ContentItemStatus.PREVIEW_READY:
            if self.policy.requires_preview_approval(
                strategy.approval_policy
            ) or self.policy.requires_publish_approval(strategy.approval_policy):
                await ApprovalManager(self.session, policy=self.policy).request(
                    item.id, ApprovalCheckpoint.BEFORE_PUBLISH
                )
            else:
                item.status = ContentItemStatus.READY_TO_PUBLISH
                await self.session.commit()
        return item

    async def publish_if_allowed(self, item_id: uuid.UUID) -> ContentItem:
        item = await self.session.get(ContentItem, item_id)
        if item is None:
            raise ValueError("ContentItem not found")
        strategy = await self.session.get(ContentStrategy, item.strategy_id)
        if strategy is None:
            raise ValueError("ContentStrategy not found")
        if item.status != ContentItemStatus.READY_TO_PUBLISH:
            return item
        if not (self.fake and (strategy.auto_publish and self.settings.operations_auto_publish)):
            return item
        item.status = ContentItemStatus.PUBLISHING
        await self.session.commit()
        item.status = ContentItemStatus.PUBLISHED
        item.completed_at = datetime.now(UTC)
        await audit(
            self.session,
            "content_published",
            strategy_id=item.strategy_id,
            project_id=item.project_id,
            content_item_id=item.id,
            rationale="fake publisher completed",
        )
        await self.session.commit()
        return item

    async def _failure(
        self, item: ContentItem, error_class: ErrorClass, message: str
    ) -> ContentItem:
        item.retry_count += 1
        item.failure_report = {
            "stage": item.current_stage,
            "attempts": item.attempts,
            "error_code": error_class.value,
            "last_error": message,
            "recoverable": error_class
            in {ErrorClass.TEMPORARY, ErrorClass.RATE_LIMIT, ErrorClass.EXTERNAL_DEPENDENCY},
        }
        if item.retry_count <= self.policy.max_producer_retries and error_class in {
            ErrorClass.TEMPORARY,
            ErrorClass.RATE_LIMIT,
            ErrorClass.EXTERNAL_DEPENDENCY,
        }:
            item.status = ContentItemStatus.QUEUED
            await audit(
                self.session,
                "retry_scheduled",
                strategy_id=item.strategy_id,
                project_id=item.project_id,
                content_item_id=item.id,
                rationale=message,
                data={"retry_count": item.retry_count},
            )
        else:
            item.status = ContentItemStatus.MANUAL_REQUIRED
            await audit(
                self.session,
                "retry_exhausted",
                strategy_id=item.strategy_id,
                project_id=item.project_id,
                content_item_id=item.id,
                rationale=message,
            )
        await self.session.commit()
        return item
