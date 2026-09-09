import uuid

import structlog
from celery import Task  # type: ignore[import-untyped]

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.models import SourceItem, User, VideoProject
from app.services.errors import TemporaryProcessingError
from app.services.platform_variant_media import PlatformVariantMediaService
from app.services.preview_delivery import PreviewDeliveryService
from app.services.production_rendering import ProductionRenderService
from app.services.rendering_factory import create_render_service
from app.services.runtime_settings import SettingsService
from app.services.video_editor import FFmpegVideoEditor
from app.storage.local import LocalStorage
from app.tasks.celery_app import celery_app
from app.tasks.processing import run_async

logger = structlog.get_logger()


async def render_production_once(production_project_id: uuid.UUID, profile: str) -> VideoProject:
    settings = get_settings()
    async with SessionFactory() as session:
        settings = await SettingsService(session, settings).resolved()
        return await ProductionRenderService(
            session, LocalStorage(settings.media_root), settings
        ).render(production_project_id, profile_name=profile)


@celery_app.task(name="content_factory.render_production", max_retries=1)
def render_production_task(production_project_id: str, profile: str = "preview") -> str:
    project = run_async(render_production_once(uuid.UUID(production_project_id), profile))
    try:
        run_async(notify_render(project.id, True))
    except Exception:
        logger.exception("production_preview_notification_failed", production_project_id=production_project_id)
    return str(project.id)


async def render_video_once(video_project_id: uuid.UUID, fingerprint: str) -> VideoProject:
    settings = get_settings()
    async with SessionFactory() as session:
        settings = await SettingsService(session, settings).resolved()
        return await create_render_service(session, settings).render(video_project_id, fingerprint)


async def notify_render(video_project_id: uuid.UUID, success: bool) -> None:
    settings = get_settings()
    async with SessionFactory() as session:
        project = await session.get(VideoProject, video_project_id)
        if project is None:
            return
        source = await session.get(SourceItem, project.source_item_id)
        if source is None:
            return
        user = await session.get(User, source.user_id)
        if user is None:
            return
        delivery = PreviewDeliveryService(
            bot_token=settings.telegram_bot_token,
            storage=LocalStorage(settings.media_root),
            maximum_size_bytes=settings.telegram_preview_max_size_mb * 1024 * 1024,
            editor=FFmpegVideoEditor(font_path=settings.video_font_path),
            proxy_url=settings.telegram_proxy_url,
        )
        try:
            if success:
                preview_path = await delivery.deliver(
                    project, source.telegram_chat_id or user.telegram_id
                )
                if preview_path and preview_path != project.preview_path:
                    project.preview_path = preview_path
                    await session.commit()
            else:
                await delivery.failed(project, source.telegram_chat_id or user.telegram_id)
        finally:
            await delivery.aclose()


@celery_app.task(bind=True, name="content_factory.render_video", max_retries=1)
def render_video_task(task: Task, video_project_id: str, fingerprint: str) -> str:
    parsed_id = uuid.UUID(video_project_id)
    try:
        project = run_async(render_video_once(parsed_id, fingerprint))
    except TemporaryProcessingError as exc:
        retries = int(getattr(task.request, "retries", 0))
        if retries < 1:
            raise task.retry(exc=exc, countdown=10) from exc
        run_async(notify_render(parsed_id, False))
        return "failed"
    except Exception:
        run_async(notify_render(parsed_id, False))
        raise
    try:
        run_async(notify_render(parsed_id, True))
    except Exception:
        logger.exception("video_preview_notification_failed", video_project_id=video_project_id)
    logger.info("video_render_task_completed", video_project_id=video_project_id)
    return project.status.value


async def render_platform_variant_once(
    video_project_id: uuid.UUID, fingerprint: str, variant_id: uuid.UUID
) -> VideoProject:
    project = await render_video_once(video_project_id, fingerprint)
    async with SessionFactory() as session:
        await PlatformVariantMediaService(session).attach_rendered(variant_id, video_project_id)
    return project


@celery_app.task(name="content_factory.render_platform_variant", max_retries=1)
def render_platform_variant_task(
    task: Task, video_project_id: str, fingerprint: str, variant_id: str
) -> str:
    project = run_async(
        render_platform_variant_once(
            uuid.UUID(video_project_id), fingerprint, uuid.UUID(variant_id)
        )
    )
    return project.status.value
