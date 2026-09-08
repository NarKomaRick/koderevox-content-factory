from pathlib import Path
from typing import Protocol

from app.models import ContentDraft
from app.schemas.processing import TranscriptionResult


class SpeechToTextProvider(Protocol):
    async def transcribe(
        self, media_path: Path, vocabulary: list[str] | None = None
    ) -> TranscriptionResult: ...


class ImageUnderstandingProvider(Protocol):
    async def describe(self, image_path: Path, user_context: str | None = None) -> str: ...


class Publisher(Protocol):
    async def publish(self, content: ContentDraft) -> str: ...


class ExternalAssetProvider(Protocol):
    """Phase 5+ extension point. Phase 4 never searches stock automatically."""

    async def search(self, query: str, *, license_types: list[str]) -> list[dict[str, str]]: ...


class MusicProvider(Protocol):
    """Extension point for explicitly selected, licensed local background audio."""

    async def resolve(self, asset_id: str) -> Path: ...
