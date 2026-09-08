from app.core.config import Settings
from app.models.enums import PublishingPlatform
from app.services.publishers.registry import PublisherRegistry
from app.services.publishers.telegram import TelegramPublisher
from app.services.publishers.tiktok import TikTokPublisher
from app.services.publishers.youtube import YouTubePublisher


def create_publisher_registry(settings: Settings) -> PublisherRegistry:
    registry = PublisherRegistry()
    registry.register(
        PublishingPlatform.TELEGRAM,
        TelegramPublisher(settings.telegram_publish_bot_token or settings.telegram_bot_token),
    )
    registry.register(
        PublishingPlatform.YOUTUBE,
        YouTubePublisher(encryption_key=settings.credential_encryption_key),
    )
    registry.register(PublishingPlatform.TIKTOK, TikTokPublisher())
    return registry
