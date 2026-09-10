from __future__ import annotations

import asyncio

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.operations.orchestrator import StudioOrchestrator
from app.tasks.celery_app import celery_app


@celery_app.task(name="content_factory.operations.tick")
def operations_tick() -> dict[str, int | bool]:
    return asyncio.run(_run_tick())


async def _run_tick() -> dict[str, int | bool]:
    async with SessionFactory() as session:
        return await StudioOrchestrator(session, get_settings()).run_once()
