from app.models.enums import PublishingPlatform
from app.services.publishers.base import Publisher


class PublisherRegistry:
    def __init__(self) -> None:
        self._publishers: dict[PublishingPlatform, Publisher] = {}

    def register(self, platform: PublishingPlatform, publisher: Publisher) -> None:
        self._publishers[platform] = publisher

    def get(self, platform: PublishingPlatform) -> Publisher:
        try:
            return self._publishers[platform]
        except KeyError as exc:
            raise LookupError(f"Publisher is not configured for {platform.value}") from exc

    def supports(self, platform: PublishingPlatform) -> bool:
        return platform in self._publishers

    async def aclose(self) -> None:
        for publisher in self._publishers.values():
            close = getattr(publisher, "aclose", None)
            if close is not None:
                await close()
