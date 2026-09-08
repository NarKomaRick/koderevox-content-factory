import asyncio

import structlog

from app.core.config import get_settings
from app.core.logging import configure_logging
from app.db.session import SessionFactory
from app.services.publication_scheduler import PublicationScheduler
from app.services.publications import PublicationService
from app.services.publisher_factory import create_publisher_registry
from app.tasks.queue import CeleryPublicationTaskQueue

logger = structlog.get_logger()


async def tick() -> int:
    settings = get_settings()
    queue = CeleryPublicationTaskQueue()
    registry = create_publisher_registry(settings)
    try:
        async with SessionFactory() as session:
            scheduler = PublicationScheduler(session)
            due = await scheduler.claim_due()
            processing = await scheduler.due_processing()
            queued = list(dict.fromkeys([*due, *(await scheduler.unclaimed_queued())]))
            service = PublicationService(session, registry, media_root=settings.media_root)
            for publication_id in queued:
                task_id = queue.enqueue(publication_id)
                await service.mark_task_enqueued(publication_id, task_id)
            for publication_id in processing:
                queue.enqueue_poll(publication_id)
            await service.recover_stale_claims()
            return len(queued) + len(processing)
    finally:
        await registry.aclose()


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    while True:
        try:
            count = await tick()
            if count:
                await logger.ainfo("publishing_scheduler_tick", enqueued=count)
        except Exception:
            await logger.aexception("publishing_scheduler_failed")
        await asyncio.sleep(settings.publish_scheduler_interval_seconds)


if __name__ == "__main__":
    asyncio.run(run())
