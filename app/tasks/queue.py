import uuid
from typing import Protocol

import structlog

from app.tasks.autonomous_director import run_autonomous_director_task
from app.tasks.director import run_director_task
from app.tasks.processing import process_source_note_task, process_source_task
from app.tasks.producer import run_producer_task
from app.tasks.publishing import poll_publication_task, publish_publication_task
from app.tasks.rendering import (
    render_platform_variant_task,
    render_production_task,
    render_video_task,
)

logger = structlog.get_logger()


class SourceTaskQueue(Protocol):
    def enqueue(self, source_id: uuid.UUID) -> str: ...

    def enqueue_note(self, note_id: uuid.UUID) -> str: ...


class CelerySourceTaskQueue:
    def enqueue(self, source_id: uuid.UUID) -> str:
        result = process_source_task.apply_async(args=[str(source_id)], queue="media")
        logger.info("source_processing_enqueued", source_id=str(source_id), task_id=str(result.id))
        return str(result.id)

    def enqueue_note(self, note_id: uuid.UUID) -> str:
        result = process_source_note_task.apply_async(args=[str(note_id)], queue="media")
        logger.info("source_note_processing_enqueued", note_id=str(note_id), task_id=str(result.id))
        return str(result.id)


class VideoRenderTaskQueue(Protocol):
    def enqueue(self, video_project_id: uuid.UUID, fingerprint: str) -> str: ...

    def enqueue_platform_variant(
        self, video_project_id: uuid.UUID, fingerprint: str, variant_id: uuid.UUID
    ) -> str: ...


class CeleryVideoRenderTaskQueue:
    def enqueue(self, video_project_id: uuid.UUID, fingerprint: str) -> str:
        result = render_video_task.apply_async(
            args=[str(video_project_id), fingerprint], queue="render"
        )
        logger.info(
            "video_render_enqueued",
            video_project_id=str(video_project_id),
            task_id=str(result.id),
        )
        return str(result.id)

    def enqueue_platform_variant(
        self, video_project_id: uuid.UUID, fingerprint: str, variant_id: uuid.UUID
    ) -> str:
        result = render_platform_variant_task.apply_async(
            args=[str(video_project_id), fingerprint, str(variant_id)], queue="render"
        )
        return str(result.id)


class ProductionRenderTaskQueue(Protocol):
    def enqueue(self, production_project_id: uuid.UUID, profile: str) -> str: ...


class CeleryProductionRenderTaskQueue:
    def enqueue(self, production_project_id: uuid.UUID, profile: str) -> str:
        result = render_production_task.apply_async(
            args=[str(production_project_id), profile], queue="render"
        )
        logger.info(
            "production_render_enqueued",
            production_project_id=str(production_project_id),
            profile=profile,
            task_id=str(result.id),
        )
        return str(result.id)


class DirectorTaskQueue(Protocol):
    def enqueue(self, run_id: uuid.UUID) -> str: ...


class CeleryDirectorTaskQueue:
    def enqueue(self, run_id: uuid.UUID) -> str:
        result = run_director_task.apply_async(args=[str(run_id)], queue="director")
        logger.info("director_enqueued", run_id=str(run_id), task_id=str(result.id))
        return str(result.id)


class AutonomousDirectorTaskQueue(Protocol):
    def enqueue(self, run_id: uuid.UUID) -> str: ...


class CeleryAutonomousDirectorTaskQueue:
    def enqueue(self, run_id: uuid.UUID) -> str:
        result = run_autonomous_director_task.apply_async(args=[str(run_id)], queue="director")
        logger.info("autonomous_director_enqueued", run_id=str(run_id), task_id=str(result.id))
        return str(result.id)


class ProducerTaskQueue(Protocol):
    def enqueue(self, run_id: uuid.UUID) -> str: ...


class CeleryProducerTaskQueue:
    def enqueue(self, run_id: uuid.UUID) -> str:
        result = run_producer_task.apply_async(args=[str(run_id)], queue="producer")
        logger.info("producer_enqueued", run_id=str(run_id), task_id=str(result.id))
        return str(result.id)


class PublicationTaskQueue(Protocol):
    def enqueue(self, publication_id: uuid.UUID) -> str: ...

    def enqueue_poll(self, publication_id: uuid.UUID) -> str: ...


class CeleryPublicationTaskQueue:
    def enqueue(self, publication_id: uuid.UUID) -> str:
        result = publish_publication_task.apply_async(args=[str(publication_id)], queue="publish")
        logger.info(
            "publication_enqueued",
            publication_id=str(publication_id),
            task_id=str(result.id),
        )
        return str(result.id)

    def enqueue_poll(self, publication_id: uuid.UUID) -> str:
        result = poll_publication_task.apply_async(args=[str(publication_id)], queue="publish")
        return str(result.id)
