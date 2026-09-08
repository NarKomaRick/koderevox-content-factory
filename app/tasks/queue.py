import uuid
from typing import Protocol

import structlog

from app.tasks.processing import process_source_note_task, process_source_task
from app.tasks.rendering import render_video_task

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
