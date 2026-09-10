from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.models import ApprovalRequest, Project, User
from app.operations.approvals import ApprovalManager
from app.operations.clock import FakeClock
from app.operations.domain import ApprovalPolicy, ContentItemStatus, ensure_content_item_transition
from app.operations.orchestrator import StudioOrchestrator
from app.operations.schemas import ApprovalDecision, ContentItemCreate, PillarInput, StrategyCreate
from app.operations.service import OperationsService
from app.services.errors import InvalidStateError


@pytest.mark.asyncio
async def test_operations_planning_is_bounded_and_idempotent(session) -> None:
    project = await session.scalar(select(Project))
    user = User(telegram_id=991001)
    session.add(user)
    await session.commit()
    clock = FakeClock(datetime(2026, 9, 14, 9, tzinfo=UTC))
    settings = Settings(operations_enabled=True, operations_planning_horizon_days=14)
    service = OperationsService(session, settings, clock=clock)
    strategy = await service.create_strategy(
        StrategyCreate(
            project_id=project.id,
            user_id=user.id,
            name="Koderevox Content",
            weekly_target=3,
            approval_policy=ApprovalPolicy.BEFORE_PUBLISH,
            content_pillars=[
                PillarInput(name="AI", weight=0.35),
                PillarInput(name="Backend", weight=0.25),
                PillarInput(name="Mobile", weight=0.20),
                PillarInput(name="Automation", weight=0.20),
            ],
        )
    )
    first = await StudioOrchestrator(session, settings, clock=clock, fake=True).run_once(
        strategy_id=strategy.id
    )
    second = await StudioOrchestrator(session, settings, clock=clock, fake=True).run_once(
        strategy_id=strategy.id
    )
    items = await service.list_items(strategy_id=strategy.id)
    assert first["planned"] == 6
    assert second["planned"] == 0
    assert len(items) == 6
    assert {item.pillar for item in items} >= {"AI", "Backend"}


@pytest.mark.asyncio
async def test_operations_approval_retry_and_cancel_are_stateful(session) -> None:
    project = await session.scalar(select(Project))
    user = User(telegram_id=991002)
    session.add(user)
    await session.commit()
    clock = FakeClock(datetime(2026, 9, 14, 9, tzinfo=UTC))
    settings = Settings(operations_enabled=True, operations_max_active_items=1)
    service = OperationsService(session, settings, clock=clock)
    strategy = await service.create_strategy(
        StrategyCreate(
            project_id=project.id,
            user_id=user.id,
            name="Approval strategy",
            approval_policy=ApprovalPolicy.SCRIPT,
            content_pillars=[PillarInput(name="AI")],
        )
    )
    item = await service.create_item(
        ContentItemCreate(strategy_id=strategy.id, topic_hint="temporary-failure")
    )
    await StudioOrchestrator(session, settings, clock=clock, fake=True).run_once(
        strategy_id=strategy.id
    )
    item = await service.get_item(item.id)
    assert item.status == ContentItemStatus.QUEUED
    await StudioOrchestrator(session, settings, clock=clock, fake=True).run_once(
        strategy_id=strategy.id
    )
    item = await service.get_item(item.id)
    assert item.status == ContentItemStatus.AWAITING_SCRIPT_APPROVAL
    approval = await session.scalar(
        select(ApprovalRequest).where(ApprovalRequest.content_item_id == item.id)
    )
    await ApprovalManager(session).decide(approval.id, approved=True, data=ApprovalDecision())
    assert (await service.get_item(item.id)).status == ContentItemStatus.DIRECTOR_QUEUED
    await service.cancel_item(item.id)
    assert (await service.get_item(item.id)).status == ContentItemStatus.CANCELLED


def test_content_item_transition_map_rejects_cross_stage_jump() -> None:
    with pytest.raises(InvalidStateError, match="INVALID_TRANSITION"):
        ensure_content_item_transition(
            ContentItemStatus.PLANNED, ContentItemStatus.PUBLISHED
        )
