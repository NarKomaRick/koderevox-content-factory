"""Small, read-only feature and environment capability snapshot."""

from dataclasses import asdict, dataclass
from shutil import which

from app.core.config import Settings


@dataclass(frozen=True)
class CapabilitySnapshot:
    operations: bool
    producer: bool
    director: bool
    renderer: bool
    publishing: bool
    vision: bool

    def as_dict(self) -> dict[str, bool]:
        return asdict(self)


class CapabilityRegistry:
    """Centralizes capability checks without becoming a second runtime."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def snapshot(self) -> CapabilitySnapshot:
        return CapabilitySnapshot(
            operations=self.settings.operations_enabled,
            producer=self.settings.producer_enabled,
            director=self.settings.director_enabled,
            renderer=which("ffmpeg") is not None,
            publishing=bool(
                self.settings.credential_encryption_key or self.settings.telegram_publish_bot_token
            ),
            vision=self.settings.vision_enabled,
        )
