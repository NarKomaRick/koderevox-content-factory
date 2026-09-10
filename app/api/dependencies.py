from collections.abc import AsyncIterator
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider
from app.ai.factory import create_ai_provider
from app.core.config import get_settings
from app.db.session import get_session
from app.director.runtime import DirectorRunService
from app.services.assets import AssetService
from app.services.content import ContentService
from app.services.credentials import EncryptedCredentialProvider, TokenManager
from app.services.image_processor import ImageProcessor
from app.services.inbox import InboxService
from app.services.media import FFmpegMediaProcessor
from app.services.oauth import OAuthService
from app.services.ocr import create_ocr_provider
from app.services.platform_accounts import PlatformAccountService
from app.services.platform_adaptation import PlatformAdaptationService
from app.services.platform_variant_media import PlatformVariantMediaService
from app.services.production_projects import ProductionMaterialService, ProductionProjectService
from app.services.production_scripts import ScriptVersionService
from app.services.production_timeline import AutoAssemblyService, TimelineRevisionService
from app.services.publications import PublicationService
from app.services.publisher_factory import create_publisher_registry
from app.services.publishing_validation import PublishingValidationService
from app.services.retry_policy import RetryPolicy
from app.services.runtime_settings import SettingsService
from app.services.thumbnails import ThumbnailService
from app.services.video_projects import VideoProjectService
from app.services.vision import (
    OpenAICompatibleVisionProvider,
    PrivacyAwareVisionService,
)
from app.services.visual_plans import VisualPlanService
from app.services.voiceovers import VoiceoverService
from app.storage.local import LocalStorage
from app.tasks.queue import (
    CeleryDirectorTaskQueue,
    CeleryProductionRenderTaskQueue,
    CeleryPublicationTaskQueue,
    CelerySourceTaskQueue,
    CeleryVideoRenderTaskQueue,
    DirectorTaskQueue,
    ProductionRenderTaskQueue,
    PublicationTaskQueue,
    SourceTaskQueue,
    VideoRenderTaskQueue,
)


@lru_cache
def get_ai_provider() -> AIProvider:
    return create_ai_provider(get_settings())


async def get_runtime_ai_provider(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncIterator[AIProvider]:
    settings = await SettingsService(session, get_settings()).resolved()
    provider = create_ai_provider(settings)
    try:
        yield provider
    finally:
        close = getattr(provider, "aclose", None)
        if close is not None:
            await close()


def get_content_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    ai_provider: Annotated[AIProvider, Depends(get_runtime_ai_provider)],
) -> ContentService:
    return ContentService(session, ai_provider)


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
    ai_provider: Annotated[AIProvider, Depends(get_runtime_ai_provider)],
) -> VideoProjectService:
    return VideoProjectService(session, ai_provider, get_settings())


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
    ai_provider: Annotated[AIProvider, Depends(get_runtime_ai_provider)],
) -> VisualPlanService:
    return VisualPlanService(session, get_settings(), ai_provider)


def get_thumbnail_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ThumbnailService:
    settings = get_settings()
    return ThumbnailService(session, LocalStorage(settings.media_root), settings)


AssetDep = Annotated[AssetService, Depends(get_asset_service)]
VisualPlanDep = Annotated[VisualPlanService, Depends(get_visual_plan_service)]
ThumbnailDep = Annotated[ThumbnailService, Depends(get_thumbnail_service)]


def get_platform_adaptation_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    ai_provider: Annotated[AIProvider, Depends(get_runtime_ai_provider)],
) -> PlatformAdaptationService:
    return PlatformAdaptationService(session, ai_provider)


def get_platform_account_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlatformAccountService:
    return PlatformAccountService(session)


def get_platform_variant_media_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PlatformVariantMediaService:
    return PlatformVariantMediaService(session)


@lru_cache
def get_publisher_registry():
    return create_publisher_registry(get_settings())


async def get_publication_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncIterator[PublicationService]:
    settings = get_settings()
    credentials = EncryptedCredentialProvider(session, settings.credential_encryption_key)
    tokens = TokenManager(session, credentials, settings)
    try:
        yield PublicationService(
            session,
            get_publisher_registry(),
            retry_policy=RetryPolicy(
                max_attempts=settings.publish_max_attempts,
                delays_seconds=settings.publish_retry_delays_seconds,
            ),
            media_root=settings.media_root,
            credential_reader=tokens,
        )
    finally:
        await tokens.aclose()


async def get_publishing_validation_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncIterator[PublishingValidationService]:
    settings = get_settings()
    credentials = EncryptedCredentialProvider(session, settings.credential_encryption_key)
    tokens = TokenManager(session, credentials, settings)
    try:
        yield PublishingValidationService(
            get_publisher_registry(), media_root=settings.media_root, credential_reader=tokens
        )
    finally:
        await tokens.aclose()


async def get_oauth_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AsyncIterator[OAuthService]:
    settings = get_settings()
    credentials = EncryptedCredentialProvider(session, settings.credential_encryption_key)
    tokens = TokenManager(session, credentials, settings)
    try:
        yield OAuthService(session, settings, tokens)
    finally:
        await tokens.aclose()


@lru_cache
def get_publication_queue() -> PublicationTaskQueue:
    return CeleryPublicationTaskQueue()


PlatformAdaptationDep = Annotated[
    PlatformAdaptationService, Depends(get_platform_adaptation_service)
]
PlatformAccountDep = Annotated[PlatformAccountService, Depends(get_platform_account_service)]
PlatformVariantMediaDep = Annotated[
    PlatformVariantMediaService, Depends(get_platform_variant_media_service)
]
PublicationDep = Annotated[PublicationService, Depends(get_publication_service)]
PublishingValidationDep = Annotated[
    PublishingValidationService, Depends(get_publishing_validation_service)
]
PublicationQueueDep = Annotated[PublicationTaskQueue, Depends(get_publication_queue)]
OAuthDep = Annotated[OAuthService, Depends(get_oauth_service)]


def get_production_project_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProductionProjectService:
    return ProductionProjectService(session)


def get_production_material_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ProductionMaterialService:
    return ProductionMaterialService(session)


def get_script_version_service(
    session: Annotated[AsyncSession, Depends(get_session)],
    ai_provider: Annotated[AIProvider, Depends(get_runtime_ai_provider)],
) -> ScriptVersionService:
    return ScriptVersionService(session, ai_provider)


def get_voiceover_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VoiceoverService:
    return VoiceoverService(session)


def get_assembly_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AutoAssemblyService:
    return AutoAssemblyService(session, get_settings())


def get_timeline_revision_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TimelineRevisionService:
    return TimelineRevisionService(session)


ProductionProjectDep = Annotated[ProductionProjectService, Depends(get_production_project_service)]
ProductionMaterialDep = Annotated[
    ProductionMaterialService, Depends(get_production_material_service)
]
ScriptVersionDep = Annotated[ScriptVersionService, Depends(get_script_version_service)]
VoiceoverDep = Annotated[VoiceoverService, Depends(get_voiceover_service)]
AssemblyDep = Annotated[AutoAssemblyService, Depends(get_assembly_service)]
TimelineRevisionDep = Annotated[TimelineRevisionService, Depends(get_timeline_revision_service)]


@lru_cache
def get_production_render_queue() -> ProductionRenderTaskQueue:
    return CeleryProductionRenderTaskQueue()


ProductionRenderQueueDep = Annotated[
    ProductionRenderTaskQueue, Depends(get_production_render_queue)
]


def get_director_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> DirectorRunService:
    return DirectorRunService(session, get_settings())


@lru_cache
def get_director_queue() -> DirectorTaskQueue:
    return CeleryDirectorTaskQueue()


DirectorDep = Annotated[DirectorRunService, Depends(get_director_service)]
DirectorQueueDep = Annotated[DirectorTaskQueue, Depends(get_director_queue)]
