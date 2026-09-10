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
from app.operations.domain import (
    ApprovalCheckpoint,
    ContentItemStatus,
    ErrorClass,
    ensure_content_item_transition,
)
from app.operations.policies import OperationsPolicy
from app.producer.runtime import ProducerRuntime, ProducerService
from app.progress import ProgressReporter
from app.schemas.producer import ProducerRunCreate
from app.services.retry_policy import RetryPolicy


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
            ensure_content_item_transition(item.status, ContentItemStatus.QUEUED)
            item.status = ContentItemStatus.QUEUED
        item.next_retry_at = None
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
            ensure_content_item_transition(item.status, ContentItemStatus.PRODUCER_RUNNING)
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
            await ProgressReporter(
                self.session,
                "producer",
                run.id,
                source_kind="fake" if self.fake else "production",
                content_item_id=item.id,
                producer_run_id=run.id,
                min_delta=self.settings.progress_min_percent_delta,
                min_interval_seconds=self.settings.progress_update_interval_seconds,
            ).report_stage("understanding_goal", message="Понимаю задачу", force=True)
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
            ensure_content_item_transition(item.status, ContentItemStatus.PRODUCER_READY)
            item.status = ContentItemStatus.PRODUCER_READY
            await self.session.commit()
            if self.policy.requires_script_approval(strategy.approval_policy):
                await ApprovalManager(self.session, policy=self.policy).request(
                    item.id, ApprovalCheckpoint.SCRIPT
                )
                return item
        if item.status == ContentItemStatus.PRODUCER_READY:
            ensure_content_item_transition(item.status, ContentItemStatus.DIRECTOR_QUEUED)
            item.status = ContentItemStatus.DIRECTOR_QUEUED
            await self.session.commit()
        if item.status == ContentItemStatus.DIRECTOR_QUEUED:
            ensure_content_item_transition(item.status, ContentItemStatus.DIRECTOR_RUNNING)
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
                if item.production_project_id is None:
                    return await self._failure(
                        item,
                        ErrorClass.INVALID_INPUT,
                        "ProductionProject is required before Director enqueue",
                    )
                production_project_id = item.production_project_id
                from app.director.runtime import DirectorRunService
                from app.tasks.queue import (
                    CeleryAutonomousDirectorTaskQueue,
                    CeleryDirectorTaskQueue,
                )

                director_service = DirectorRunService(self.session, self.settings)
                director_run = await director_service.status(production_project_id)
                if director_run is None or not director_run.active:
                    director_run = await director_service.start(
                        production_project_id,
                        item.topic_hint or item.title_hint or "Автономно подготовить ролик",
                    )
                await ProgressReporter(
                    self.session,
                    "director",
                    director_run.id,
                    source_kind="production",
                    content_item_id=item.id,
                    director_run_id=director_run.id,
                    production_project_id=production_project_id,
                    min_delta=self.settings.progress_min_percent_delta,
                    min_interval_seconds=self.settings.progress_update_interval_seconds,
                ).report_stage("analyzing_story", message="Анализирую историю", force=True)
                queue = (
                    CeleryAutonomousDirectorTaskQueue()
                    if strategy.autonomous_mode
                    else CeleryDirectorTaskQueue()
                )
                queue.enqueue(director_run.id)
                item.status = ContentItemStatus.DIRECTOR_RUNNING
                await self.session.commit()
                return item
            director_progress = ProgressReporter(
                self.session,
                "director",
                f"content-item:{item.id}",
                source_kind="fake",
                content_item_id=item.id,
                production_project_id=item.production_project_id,
            )
            await director_progress.report_stage(
                "assembling", message="Собираю rough cut", force=True
            )
            await director_progress.complete(message="Fake Director завершил работу")
            render_progress = ProgressReporter(
                self.session,
                "render",
                f"content-item:{item.id}",
                source_kind="fake",
                content_item_id=item.id,
                production_project_id=item.production_project_id,
            )
            await render_progress.report_stage("render", message="Рендерю preview", force=True)
            await render_progress.complete(message="Fake render завершён")
            ensure_content_item_transition(item.status, ContentItemStatus.PREVIEW_READY)
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
                ensure_content_item_transition(item.status, ContentItemStatus.READY_TO_PUBLISH)
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
        ensure_content_item_transition(item.status, ContentItemStatus.PUBLISHING)
        item.status = ContentItemStatus.PUBLISHING
        await self.session.commit()
        ensure_content_item_transition(item.status, ContentItemStatus.PUBLISHED)
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
        retryable = error_class in {
            ErrorClass.TEMPORARY,
            ErrorClass.RATE_LIMIT,
            ErrorClass.EXTERNAL_DEPENDENCY,
        }
        retry = RetryPolicy(
            max_attempts=self.policy.max_producer_retries + 1,
            delays_seconds=self.settings.operations_retry_delays_seconds,
            jitter_ratio=0,
        ).decide_for(item.retry_count, retryable=retryable)
        item.failure_report = {
            "stage": item.current_stage,
            "attempts": item.attempts,
            "error_code": error_class.value,
            "last_error": message,
            "recoverable": error_class
            in {ErrorClass.TEMPORARY, ErrorClass.RATE_LIMIT, ErrorClass.EXTERNAL_DEPENDENCY},
        }
        if retry.retry:
            retry_at = datetime.now(UTC) if self.fake else retry.retry_at
            item.next_retry_at = retry_at
            item.failure_report["next_retry_at"] = retry_at.isoformat() if retry_at else None
            ensure_content_item_transition(item.status, ContentItemStatus.QUEUED)
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
            item.next_retry_at = None
            ensure_content_item_transition(item.status, ContentItemStatus.MANUAL_REQUIRED)
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
