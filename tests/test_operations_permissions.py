import pytest
from sqlalchemy import select

from app.models import Project, User
from app.operations.schemas import ContentItemCreate, PillarInput, StrategyCreate
from app.operations.service import OperationsService
from app.services.errors import PermissionDenied


@pytest.mark.asyncio
async def test_operations_service_scopes_strategies_and_items_to_actor(session) -> None:
    project = await session.scalar(select(Project))
    owner = User(telegram_id=992001)
    other = User(telegram_id=992002)
    session.add_all([owner, other])
    await session.commit()

    unscoped = OperationsService(session)
    strategy = await unscoped.create_strategy(
        StrategyCreate(
            project_id=project.id,
            user_id=owner.id,
            name="Owner strategy",
            content_pillars=[PillarInput(name="AI")],
        )
    )
    item = await unscoped.create_item(
        ContentItemCreate(strategy_id=strategy.id, topic_hint="private topic")
    )

    scoped = OperationsService(session, actor_user_id=other.id)
    assert await scoped.list_strategies() == []
    assert await scoped.list_items() == []
    with pytest.raises(PermissionDenied, match="STRATEGY_ACCESS_DENIED"):
        await scoped.get_strategy(strategy.id)
    with pytest.raises(PermissionDenied, match="CONTENT_ITEM_ACCESS_DENIED"):
        await scoped.get_item(item.id)


@pytest.mark.asyncio
async def test_operations_service_rejects_strategy_creation_for_another_actor(session) -> None:
    project = await session.scalar(select(Project))
    owner = User(telegram_id=992003)
    actor = User(telegram_id=992004)
    session.add_all([owner, actor])
    await session.commit()

    scoped = OperationsService(session, actor_user_id=actor.id)
    with pytest.raises(PermissionDenied, match="STRATEGY_OWNER_MISMATCH"):
        await scoped.create_strategy(
            StrategyCreate(
                project_id=project.id,
                user_id=owner.id,
                name="Cross-user strategy",
                content_pillars=[PillarInput(name="Backend")],
            )
        )
