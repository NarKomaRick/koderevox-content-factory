from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider
from app.ai.factory import create_ai_provider
from app.core.config import get_settings
from app.db.session import get_session
from app.services.content import ContentService
from app.services.inbox import InboxService
from app.services.video_projects import VideoProjectService
from app.tasks.queue import (
    CelerySourceTaskQueue,
    CeleryVideoRenderTaskQueue,
    SourceTaskQueue,
    VideoRenderTaskQueue,
)


@lru_cache
def get_ai_provider() -> AIProvider:
    return create_ai_provider(get_settings())


def get_content_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContentService:
    return ContentService(session, get_ai_provider())


ServiceDep = Annotated[ContentService, Depends(get_content_service)]


def get_inbox_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> InboxService:
    return InboxService(session)


@lru_cache
def get_source_task_queue() -> SourceTaskQueue:
    return CelerySourceTaskQueue()


InboxDep = Annotated[InboxService, Depends(get_inbox_service)]
QueueDep = Annotated[SourceTaskQueue, Depends(get_source_task_queue)]


def get_video_project_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VideoProjectService:
    return VideoProjectService(session, get_ai_provider(), get_settings())


@lru_cache
def get_video_render_queue() -> VideoRenderTaskQueue:
    return CeleryVideoRenderTaskQueue()


VideoProjectDep = Annotated[VideoProjectService, Depends(get_video_project_service)]
VideoQueueDep = Annotated[VideoRenderTaskQueue, Depends(get_video_render_queue)]
