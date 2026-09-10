from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import ApprovalRequest, ContentItem
from app.operations.audit import audit
from app.operations.domain import (
    ApprovalCheckpoint,
    ApprovalStatus,
    ContentItemStatus,
    ensure_content_item_transition,
)
from app.operations.policies import OperationsPolicy
from app.operations.schemas import ApprovalDecision
from app.services.errors import NotFoundError


class ApprovalManager:
    def __init__(self, session: AsyncSession, *, policy: OperationsPolicy | None = None) -> None:
        self.session = session
        self.policy = policy or OperationsPolicy.from_settings(get_settings())

    async def request(self, item_id: uuid.UUID, checkpoint: ApprovalCheckpoint) -> ApprovalRequest:
        item = await self.session.get(ContentItem, item_id)
        if item is None:
            raise NotFoundError("ContentItem not found")
        existing = await self.session.scalar(
            select(ApprovalRequest).where(
                ApprovalRequest.content_item_id == item_id, ApprovalRequest.checkpoint == checkpoint
            )
        )
        if existing and existing.status == ApprovalStatus.PENDING:
            return existing
        approval = existing or ApprovalRequest(content_item_id=item_id, checkpoint=checkpoint)
        approval.status = ApprovalStatus.PENDING
        approval.requested_at = datetime.now(UTC)
        self.session.add(approval)
        item.approval_state = ApprovalStatus.PENDING
        target_status = (
            ContentItemStatus.AWAITING_SCRIPT_APPROVAL
            if checkpoint == ApprovalCheckpoint.SCRIPT
            else ContentItemStatus.AWAITING_PREVIEW_APPROVAL
        )
        ensure_content_item_transition(item.status, target_status)
        item.status = target_status
        await audit(
            self.session,
            "approval_requested",
            strategy_id=item.strategy_id,
            project_id=item.project_id,
            content_item_id=item.id,
            rationale=f"checkpoint={checkpoint}",
        )
        await self.session.commit()
        return approval

    async def decide(
        self, approval_id: uuid.UUID, *, approved: bool, data: ApprovalDecision
    ) -> ApprovalRequest:
        approval = await self.session.get(ApprovalRequest, approval_id)
        if approval is None:
            raise NotFoundError("Approval request not found")
        if approval.status != ApprovalStatus.PENDING:
            return approval
        item = await self.session.get(ContentItem, approval.content_item_id)
        if item is None:
            raise NotFoundError("ContentItem not found")
        approval.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
        approval.responded_at = datetime.now(UTC)
        approval.actor_user_id = data.actor_user_id
        approval.comment = data.comment
        if approved:
            item.approval_state = ApprovalStatus.APPROVED
            target_status = (
                ContentItemStatus.DIRECTOR_QUEUED
                if approval.checkpoint == ApprovalCheckpoint.SCRIPT
                else ContentItemStatus.READY_TO_PUBLISH
            )
            ensure_content_item_transition(item.status, target_status)
            item.status = target_status
            event = "approval_approved"
        else:
            item.approval_state = ApprovalStatus.REJECTED
            ensure_content_item_transition(item.status, ContentItemStatus.QUEUED)
            item.status = ContentItemStatus.QUEUED
            item.correction_instruction = data.comment
            item.operator_notes = (
                [*item.operator_notes, data.comment] if data.comment else item.operator_notes
            )
            event = "approval_rejected"
        await audit(
            self.session,
            event,
            strategy_id=item.strategy_id,
            project_id=item.project_id,
            content_item_id=item.id,
            rationale=data.comment or "approval decision",
        )
        await self.session.commit()
        return approval
