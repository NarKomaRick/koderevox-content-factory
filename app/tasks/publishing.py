import uuid

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.models import ContentItem, ProductionProject, Publication, PublishPackage
from app.operations.callbacks import OperationsExecutionCallbacks
from app.progress import ProgressReporter
from app.services.credentials import EncryptedCredentialProvider, TokenManager
from app.services.publication_notifications import PublicationNotificationService
from app.services.publications import PublicationService
from app.services.publisher_factory import create_publisher_registry
from app.services.retry_policy import RetryPolicy
from app.tasks.celery_app import celery_app
from app.tasks.processing import run_async

logger = structlog.get_logger()


async def _publication_progress(
    session: AsyncSession, publication_id: uuid.UUID
) -> ProgressReporter:
    content_item_id = await session.scalar(
        select(ContentItem.id)
        .join(ProductionProject, ContentItem.production_project_id == ProductionProject.id)
        .join(
            PublishPackage,
            PublishPackage.video_project_id == ProductionProject.active_video_project_id,
        )
        .join(Publication, Publication.publish_package_id == PublishPackage.id)
        .where(Publication.id == publication_id)
    )
    reporter = ProgressReporter(
        session,
        "publish",
        publication_id,
        source_kind="production",
        content_item_id=content_item_id,
        min_delta=get_settings().progress_min_percent_delta,
        min_interval_seconds=get_settings().progress_update_interval_seconds,
    )
    await reporter.report_stage("publishing", message="Публикую на платформе", force=True)
    return reporter


async def publish_once(publication_id: uuid.UUID) -> Publication:
    settings = get_settings()
    registry = create_publisher_registry(settings)
    try:
        async with SessionFactory() as session:
            reporter = await _publication_progress(session, publication_id)
            tokens = TokenManager(
                session,
                EncryptedCredentialProvider(session, settings.credential_encryption_key),
                settings,
            )
            service = PublicationService(
                session,
                registry,
                retry_policy=RetryPolicy(
                    max_attempts=settings.publish_max_attempts,
                    delays_seconds=settings.publish_retry_delays_seconds,
                ),
                media_root=settings.media_root,
                credential_reader=tokens,
            )
            try:
                try:
                    publication = await service.execute(publication_id)
                    await OperationsExecutionCallbacks(session, settings).publication_finished(
                        publication_id
                    )
                    await reporter.complete(message="Публикация завершена")
                except Exception as exc:
                    await reporter.fail(error_code=type(exc).__name__, message=str(exc)[:2000])
                    raise
                notifier = PublicationNotificationService(
                    session,
                    settings.telegram_bot_token,
                    proxy_url=settings.telegram_proxy_url,
                )
                try:
                    await notifier.notify_if_settled(publication.publish_package_id)
                finally:
                    await notifier.aclose()
                return publication
            finally:
                await tokens.aclose()
    finally:
        await registry.aclose()


@celery_app.task(name="content_factory.publish")
def publish_publication_task(publication_id: str) -> str:
    publication = run_async(publish_once(uuid.UUID(publication_id)))
    logger.info(
        "publication_task_completed",
        publication_id=publication_id,
        status=publication.status.value,
    )
    return publication.status.value


async def poll_once(publication_id: uuid.UUID) -> Publication:
    settings = get_settings()
    registry = create_publisher_registry(settings)
    try:
        async with SessionFactory() as session:
            reporter = await _publication_progress(session, publication_id)
            tokens = TokenManager(
                session,
                EncryptedCredentialProvider(session, settings.credential_encryption_key),
                settings,
            )
            service = PublicationService(
                session,
                registry,
                media_root=settings.media_root,
                credential_reader=tokens,
            )
            try:
                try:
                    publication = await service.poll_status(publication_id)
                    await reporter.complete(message="Статус публикации обновлён")
                except Exception as exc:
                    await reporter.fail(error_code=type(exc).__name__, message=str(exc)[:2000])
                    raise
                notifier = PublicationNotificationService(
                    session,
                    settings.telegram_bot_token,
                    proxy_url=settings.telegram_proxy_url,
                )
                try:
                    await notifier.notify_if_settled(publication.publish_package_id)
                finally:
                    await notifier.aclose()
                return publication
            finally:
                await tokens.aclose()
    finally:
        await registry.aclose()


@celery_app.task(name="content_factory.poll_publication")
def poll_publication_task(publication_id: str) -> str:
    publication = run_async(poll_once(uuid.UUID(publication_id)))
    return publication.status.value
