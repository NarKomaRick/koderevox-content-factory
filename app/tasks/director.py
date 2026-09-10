"""Celery entrypoint for long-running Director runs."""

import uuid

import structlog

from app.ai.factory import create_ai_provider
from app.core.config import get_settings
from app.db.session import SessionFactory
from app.director.agent import DirectorAgent, create_director_model
from app.director.runtime import DirectorRuntime
from app.models import DirectorRun
from app.operations.callbacks import OperationsExecutionCallbacks
from app.services.runtime_settings import SettingsService
from app.tasks.celery_app import celery_app
from app.tasks.processing import run_async

logger = structlog.get_logger()


async def run_director_once(run_id: uuid.UUID) -> DirectorRun:
    settings = get_settings()
    async with SessionFactory() as session:
        run = await session.get(DirectorRun, run_id)
        if run is None:
            raise ValueError("Director run not found")
        settings = await SettingsService(session, settings).resolved()
        provider = create_ai_provider(settings)
        try:
            runtime = DirectorRuntime(session, run.production_project_id, settings)
            model = create_director_model(settings, provider)
            result = await DirectorAgent(runtime, model, settings).run(run)
            await OperationsExecutionCallbacks(session, settings).director_finished(run_id)
            return result
        finally:
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()


@celery_app.task(name="content_factory.run_director", max_retries=1)
def run_director_task(run_id: str) -> str:
    run = run_async(run_director_once(uuid.UUID(run_id)))
    logger.info("director_completed", run_id=run_id, status=run.status)
    return run.status
