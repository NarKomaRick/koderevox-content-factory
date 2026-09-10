from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import ContentItem, ContentStrategy, DirectorRun, ProducerRun
from app.operations.approvals import ApprovalManager
from app.operations.audit import audit
from app.operations.domain import (
    ApprovalCheckpoint,
    ContentItemStatus,
    ensure_content_item_transition,
)
from app.operations.policies import OperationsPolicy


class OperationsExecutionCallbacks:
    """Reconcile runtime completion back into the operational ContentItem state."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or Settings()
        self.policy = OperationsPolicy.from_settings(self.settings)

    async def producer_finished(self, run_id: uuid.UUID) -> ContentItem | None:
        run = await self.session.get(ProducerRun, run_id)
        if run is None:
            return None
        item = await self.session.scalar(
            select(ContentItem).where(ContentItem.producer_run_id == run.id)
        )
        if item is None or item.status in {
            ContentItemStatus.CANCELLED,
            ContentItemStatus.PUBLISHED,
        }:
            return item
        strategy = await self.session.get(ContentStrategy, item.strategy_id)
        if strategy is None:
            return item
        if run.status == "completed":
            item.production_project_id = run.production_project_id
            if item.status != ContentItemStatus.PRODUCER_RUNNING:
                return item
            if self.policy.requires_script_approval(strategy.approval_policy):
                ensure_content_item_transition(
                    item.status, ContentItemStatus.AWAITING_SCRIPT_APPROVAL
                )
                item.status = ContentItemStatus.AWAITING_SCRIPT_APPROVAL
                await ApprovalManager(self.session, policy=self.policy).request(
                    item.id, ApprovalCheckpoint.SCRIPT
                )
            else:
                ensure_content_item_transition(item.status, ContentItemStatus.DIRECTOR_QUEUED)
                item.status = ContentItemStatus.DIRECTOR_QUEUED
            await audit(
                self.session,
                "producer_completed",
                strategy_id=item.strategy_id,
                project_id=item.project_id,
                content_item_id=item.id,
                rationale="Producer task completion reconciled",
            )
        elif run.status in {"failed", "cancelled"}:
            await self._mark_failed(item, run.error or f"Producer run {run.status}")
        await self.session.commit()
        return item

    async def director_finished(self, run_id: uuid.UUID) -> ContentItem | None:
        run = await self.session.get(DirectorRun, run_id)
        if run is None:
            return None
        item = await self.session.scalar(
            select(ContentItem).where(ContentItem.production_project_id == run.production_project_id)
        )
        if item is None or item.status in {
            ContentItemStatus.CANCELLED,
            ContentItemStatus.PUBLISHED,
        }:
            return item
        strategy = await self.session.get(ContentStrategy, item.strategy_id)
        if strategy is None:
            return item
        if run.status == "completed" and item.status == ContentItemStatus.DIRECTOR_RUNNING:
            ensure_content_item_transition(item.status, ContentItemStatus.PREVIEW_READY)
            item.status = ContentItemStatus.PREVIEW_READY
            item.current_stage = "render"
            if self.policy.requires_preview_approval(
                strategy.approval_policy
            ) or self.policy.requires_publish_approval(strategy.approval_policy):
                checkpoint = (
                    ApprovalCheckpoint.PREVIEW
                    if self.policy.requires_preview_approval(strategy.approval_policy)
                    else ApprovalCheckpoint.BEFORE_PUBLISH
                )
                await ApprovalManager(self.session, policy=self.policy).request(
                    item.id, checkpoint
                )
            else:
                ensure_content_item_transition(item.status, ContentItemStatus.READY_TO_PUBLISH)
                item.status = ContentItemStatus.READY_TO_PUBLISH
            await audit(
                self.session,
                "director_completed",
                strategy_id=item.strategy_id,
                project_id=item.project_id,
                content_item_id=item.id,
                rationale="Director task completion reconciled",
            )
        elif run.status == "failed":
            await self._mark_failed(item, run.error or "Director run failed")
        await self.session.commit()
        return item

    async def _mark_failed(self, item: ContentItem, message: str) -> None:
        if item.status not in {
            ContentItemStatus.PRODUCER_RUNNING,
            ContentItemStatus.DIRECTOR_RUNNING,
        }:
            return
        ensure_content_item_transition(item.status, ContentItemStatus.FAILED)
        item.status = ContentItemStatus.FAILED
        item.failure_report = {
            **item.failure_report,
            "stage": item.current_stage,
            "last_error": message[:2000],
            "recoverable": True,
        }
