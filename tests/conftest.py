from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db.base import Base
from app.models import Project


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as db_session:
        db_session.add(
            Project(
                name="Koderevox",
                description="Студия разработки цифровых продуктов",
                brand_context="Инженерная студия. Без пафоса и AI-slop.",
                target_audience="Владельцы бизнеса и технические руководители",
                language="ru",
            )
        )
        await db_session.commit()
        yield db_session
    await engine.dispose()
