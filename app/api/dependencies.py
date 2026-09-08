from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider
from app.ai.factory import create_ai_provider
from app.core.config import get_settings
from app.db.session import get_session
from app.services.assets import AssetService
from app.services.content import ContentService
from app.services.image_processor import ImageProcessor
from app.services.inbox import InboxService
from app.services.media import FFmpegMediaProcessor
from app.services.ocr import create_ocr_provider
from app.services.thumbnails import ThumbnailService
from app.services.video_projects import VideoProjectService
from app.services.vision import (
    OpenAICompatibleVisionProvider,
    PrivacyAwareVisionService,
)
from app.services.visual_plans import VisualPlanService
from app.storage.local import LocalStorage
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


def get_asset_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AssetService:
    settings = get_settings()
    vision = None
    if settings.vision_enabled:
        provider = OpenAICompatibleVisionProvider(
            base_url=settings.vision_base_url,
            api_key=settings.vision_api_key,
            model=settings.vision_model,
            timeout=settings.vision_timeout_seconds,
        )
        vision = PrivacyAwareVisionService(provider)
    return AssetService(
        session=session,
        storage=LocalStorage(settings.media_root),
        settings=settings,
        images=ImageProcessor(settings.max_image_pixels),
        media=FFmpegMediaProcessor(),
        ocr=create_ocr_provider(enabled=settings.ocr_enabled, language=settings.ocr_language),
        vision=vision,
    )


def get_visual_plan_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VisualPlanService:
    return VisualPlanService(session, get_settings(), get_ai_provider())


def get_thumbnail_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ThumbnailService:
    settings = get_settings()
    return ThumbnailService(session, LocalStorage(settings.media_root), settings)


AssetDep = Annotated[AssetService, Depends(get_asset_service)]
VisualPlanDep = Annotated[VisualPlanService, Depends(get_visual_plan_service)]
ThumbnailDep = Annotated[ThumbnailService, Depends(get_thumbnail_service)]
