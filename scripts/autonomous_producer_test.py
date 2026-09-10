"""Offline Phase 8 capability smoke.

The --real switch is intentionally a capability probe: unavailable network or
LLM providers are reported as not_tested, not as a false pass.
"""

from __future__ import annotations

import argparse
import asyncio
import json

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.base import Base
from app.models import Project, User
from app.producer.model import FakeProducerModel
from app.producer.research import FakeResearchProvider
from app.producer.runtime import ProducerRuntime
from app.schemas.producer import ProducerRunCreate


async def fake_smoke() -> dict[str, str]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        project = Project(name="Producer smoke")
        user = User(telegram_id=999_001)
        session.add_all([project, user])
        await session.commit()
        from app.producer.runtime import ProducerService

        run = await ProducerService(session, Settings(producer_enabled=True)).create(
            ProducerRunCreate(
                prompt="Как сделать интеграцию надёжной?",
                user_id=user.id,
                project_id=project.id,
                research_mode="fixtures",
            )
        )
        runtime = ProducerRuntime(
            session,
            Settings(producer_enabled=True),
            model=FakeProducerModel(),
            research_provider=FakeResearchProvider(),
        )
        result = await runtime.run(run.id)
        if str(result.status) != "completed" or result.production_project_id is None:
            raise RuntimeError(f"fake producer did not complete: {result.status} {result.error}")
    await engine.dispose()
    return {
        "fake_producer": "passed",
        "real_producer": "not_tested",
        "real_research": "not_tested",
        "real_video_pipeline": "not_tested",
        "research_provider": "fake",
    }


async def main(real: bool) -> None:
    result = await fake_smoke()
    if real:
        # Credentials and network are intentionally not required by Phase 8.
        result["real_producer"] = "not_tested"
        result["real_research"] = "not_tested"
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--fake", action="store_true")
    parser.add_argument("--real", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.real))
