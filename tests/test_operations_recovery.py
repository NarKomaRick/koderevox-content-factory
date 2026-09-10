from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.models import ContentItem, JobProgress, Project, User
from app.operations.clock import FakeClock
from app.operations.domain import ContentItemStatus
from app.operations.recovery import RecoveryManager
from app.operations.schemas import ContentItemCreate, PillarInput, StrategyCreate
from app.operations.service import OperationsService


@pytest.mark.asyncio
async def test_recovery_uses_stage_timeout_and_persisted_heartbeat(session) -> None:
    project = await session.scalar(select(Project))
    user = User(telegram_id=991003)
    session.add(user)
    await session.commit()
    clock = FakeClock(datetime(2026, 9, 14, 9, tzinfo=UTC))
    settings = Settings(
        operations_enabled=True,
        operations_producer_stale_seconds=60,
        operations_director_stale_seconds=120,
    )
    service = OperationsService(session, settings, clock=clock)
    strategy = await service.create_strategy(
        StrategyCreate(
            project_id=project.id,
            user_id=user.id,
            name="Recovery strategy",
            content_pillars=[PillarInput(name="AI")],
        )
    )
    stale_item = await service.create_item(ContentItemCreate(strategy_id=strategy.id))
    stale_item.status = ContentItemStatus.PRODUCER_RUNNING
    stale_item.current_stage = "producer"
    stale_item.updated_at = clock.now() - timedelta(seconds=61)

    heartbeat_item = await service.create_item(ContentItemCreate(strategy_id=strategy.id))
    heartbeat_item.status = ContentItemStatus.DIRECTOR_RUNNING
    heartbeat_item.current_stage = "director"
    heartbeat_item.updated_at = clock.now() - timedelta(seconds=500)
    session.add(
        JobProgress(
            job_type="director",
            job_id="director-heartbeat",
            content_item_id=heartbeat_item.id,
            state="running",
            stage="assembling",
            updated_at=clock.now(),
        )
    )
    await session.commit()

    recovered = await RecoveryManager(session, settings, clock=clock).recover_stale()

    assert recovered == [stale_item.id]
    assert (await session.get(ContentItem, stale_item.id)).status == ContentItemStatus.QUEUED
    assert (
        await session.get(ContentItem, heartbeat_item.id)
    ).status == ContentItemStatus.DIRECTOR_RUNNING
