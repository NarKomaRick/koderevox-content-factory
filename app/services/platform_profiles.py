from app.models.enums import PublishingPlatform
from app.schemas.publishing import PlatformMediaProfile


class PlatformMediaProfiles:
    def __init__(self, overrides: dict[PublishingPlatform, PlatformMediaProfile] | None = None):
        self._profiles = {**self.defaults(), **(overrides or {})}

    @staticmethod
    def defaults() -> dict[PublishingPlatform, PlatformMediaProfile]:
        return {
            PublishingPlatform.TELEGRAM: PlatformMediaProfile(
                platform=PublishingPlatform.TELEGRAM,
                max_title_length=0,
                max_caption_length=1024,
                max_description_length=4096,
                max_file_size_bytes=2_000_000_000,
            ),
            PublishingPlatform.YOUTUBE: PlatformMediaProfile(
                platform=PublishingPlatform.YOUTUBE,
                max_title_length=100,
                max_caption_length=0,
                max_description_length=5000,
                max_file_size_bytes=256 * 1024**3,
            ),
            PublishingPlatform.TIKTOK: PlatformMediaProfile(
                platform=PublishingPlatform.TIKTOK,
                max_title_length=2200,
                max_caption_length=2200,
                max_description_length=2200,
                max_file_size_bytes=4 * 1024**3,
                thumbnail_optional=True,
                requires_clean_render=True,
            ),
        }

    def get(self, platform: PublishingPlatform) -> PlatformMediaProfile:
        return self._profiles[platform]
