from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.models import ContentItem, ProducerRun, Project, User
from app.operations.callbacks import OperationsExecutionCallbacks
from app.operations.clock import FakeClock
from app.operations.domain import ContentItemStatus
from app.operations.schemas import ContentItemCreate, PillarInput, StrategyCreate
from app.operations.service import OperationsService


@pytest.mark.asyncio
async def test_producer_completion_callback_requeues_director_once(session) -> None:
    project = await session.scalar(select(Project))
    user = User(telegram_id=991004)
    session.add(user)
    await session.commit()
    clock = FakeClock(datetime(2026, 9, 14, 9, tzinfo=UTC))
    settings = Settings(operations_enabled=True)
    service = OperationsService(session, settings, clock=clock)
    strategy = await service.create_strategy(
        StrategyCreate(
            project_id=project.id,
            user_id=user.id,
            name="Callback strategy",
            content_pillars=[PillarInput(name="AI")],
        )
    )
    item = await service.create_item(ContentItemCreate(strategy_id=strategy.id))
    item.status = ContentItemStatus.PRODUCER_RUNNING
    run = ProducerRun(
        project_id=project.id,
        user_id=user.id,
        raw_prompt="callback test",
        status="completed",
    )
    session.add(run)
    await session.flush()
    item.producer_run_id = run.id
    await session.commit()

    callback = OperationsExecutionCallbacks(session, settings)
    await callback.producer_finished(run.id)
    await callback.producer_finished(run.id)

    assert (await session.get(ContentItem, item.id)).status == ContentItemStatus.DIRECTOR_QUEUED
