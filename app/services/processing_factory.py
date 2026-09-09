from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.factory import create_ai_provider
from app.core.config import Settings
from app.services.assets import AssetService
from app.services.document_processor import DocumentProcessor
from app.services.image_processor import ImageProcessor
from app.services.link_processor import LinkProcessor
from app.services.media import FFmpegMediaProcessor
from app.services.ocr import create_ocr_provider
from app.services.processing import SourceProcessingService
from app.services.stt import FasterWhisperProvider
from app.services.telegram_media import TelegramMediaService
from app.storage.local import LocalStorage


@lru_cache(maxsize=4)
def get_stt_provider(model: str, device: str, compute_type: str) -> FasterWhisperProvider:
    """Load the expensive Whisper model once per worker process/configuration."""
    return FasterWhisperProvider(model, device, compute_type)


def create_processing_service(session: AsyncSession, settings: Settings) -> SourceProcessingService:
    storage = LocalStorage(settings.media_root)
    telegram_media = None
    if settings.telegram_bot_token:
        telegram_media = TelegramMediaService(
            bot_token=settings.telegram_bot_token,
            storage=storage,
            max_size_bytes=settings.max_media_size_mb * 1024 * 1024,
            proxy_url=settings.telegram_proxy_url,
        )
    if settings.stt_provider != "faster_whisper":
        raise ValueError(f"Unsupported STT_PROVIDER: {settings.stt_provider}")
    images = ImageProcessor(settings.max_image_pixels)
    ocr = create_ocr_provider(enabled=settings.ocr_enabled, language=settings.ocr_language)
    assets = AssetService(
        session=session,
        storage=storage,
        settings=settings,
        images=images,
        media=FFmpegMediaProcessor(),
        ocr=ocr,
        # External vision is intentionally not run by the automatic media worker.
        vision=None,
    )
    return SourceProcessingService(
        session=session,
        ai_provider=create_ai_provider(settings),
        storage=storage,
        media_processor=FFmpegMediaProcessor(),
        stt_provider=get_stt_provider(
            settings.stt_model, settings.stt_device, settings.stt_compute_type
        ),
        document_processor=DocumentProcessor(settings.document_max_chars),
        image_processor=images,
        link_processor=LinkProcessor(
            timeout_seconds=settings.link_fetch_timeout_seconds,
            max_size_bytes=settings.link_max_size_mb * 1024 * 1024,
            max_redirects=settings.link_max_redirects,
        ),
        telegram_media=telegram_media,
        asset_service=assets,
    )
