"""Celery entrypoint for bounded Producer runs."""

import uuid

import structlog

from app.ai.factory import create_ai_provider
from app.core.config import get_settings
from app.db.session import SessionFactory
from app.models import ProducerRun
from app.producer.research import FakeResearchProvider, LinkProcessorResearchProvider
from app.producer.runtime import ProducerRuntime, create_producer_model
from app.services.link_processor import LinkProcessor
from app.services.runtime_settings import SettingsService
from app.tasks.celery_app import celery_app
from app.tasks.processing import run_async

logger = structlog.get_logger()


async def run_producer_once(run_id: uuid.UUID) -> str:
    settings = get_settings()
    async with SessionFactory() as session:
        settings = await SettingsService(session, settings).resolved()
        stored_run = await session.get(ProducerRun, run_id)
        if stored_run is None:
            raise ValueError("Producer run not found")
        provider = create_ai_provider(settings)
        try:
            link_processor = LinkProcessor(
                timeout_seconds=settings.link_fetch_timeout_seconds,
                max_size_bytes=settings.producer_max_research_bytes,
                max_redirects=settings.link_max_redirects,
            )
            runtime = ProducerRuntime(
                session,
                settings,
                model=create_producer_model(settings, provider),
                research_provider=(
                    LinkProcessorResearchProvider(link_processor)
                    if stored_run.research_mode == "controlled"
                    else FakeResearchProvider()
                ),
            )
            try:
                run = await runtime.run(run_id)
                return str(run.status)
            finally:
                await link_processor.aclose()
        finally:
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()


@celery_app.task(name="content_factory.run_producer", max_retries=1)
def run_producer_task(run_id: str) -> str:
    status = run_async(run_producer_once(uuid.UUID(run_id)))
    logger.info("producer_completed", run_id=run_id, status=status)
    return status
