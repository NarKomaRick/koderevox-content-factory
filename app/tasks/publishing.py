import uuid

import structlog

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.models import Publication
from app.services.credentials import EncryptedCredentialProvider, TokenManager
from app.services.publication_notifications import PublicationNotificationService
from app.services.publications import PublicationService
from app.services.publisher_factory import create_publisher_registry
from app.services.retry_policy import RetryPolicy
from app.tasks.celery_app import celery_app
from app.tasks.processing import run_async

logger = structlog.get_logger()


async def publish_once(publication_id: uuid.UUID) -> Publication:
    settings = get_settings()
    registry = create_publisher_registry(settings)
    try:
        async with SessionFactory() as session:
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
                publication = await service.execute(publication_id)
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
                publication = await service.poll_status(publication_id)
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
