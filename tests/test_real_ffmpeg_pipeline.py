import asyncio
import shutil
from pathlib import Path

import pytest

from app.ai.mock import MockAIProvider
from app.models.enums import SourceStatus, SourceType
from app.schemas.api import SourceCreate
from app.schemas.processing import TranscriptionResult, TranscriptSegment
from app.services.document_processor import DocumentProcessor
from app.services.image_processor import ImageProcessor
from app.services.inbox import InboxService
from app.services.media import FFmpegMediaProcessor
from app.services.processing import SourceProcessingService
from app.storage.local import LocalStorage


class InspectingSTT:
    def __init__(self) -> None:
        self.received_path: Path | None = None

    async def transcribe(self, media_path: Path) -> TranscriptionResult:
        self.received_path = media_path
        assert await asyncio.to_thread(media_path.exists)
        return TranscriptionResult(
            text="Тестовая расшифровка голосового",
            language="ru",
            duration=1.0,
            segments=[TranscriptSegment(start=0, end=1, text="Тестовая расшифровка")],
        )


class NeverLink:
    async def process(self, _url: str):
        raise AssertionError("unexpected link call")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is required")
async def test_voice_pipeline_with_real_ffmpeg_cleans_temporary_wav(session, tmp_path) -> None:
    input_path = tmp_path / "voice.ogg"
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:duration=1",
        "-c:a",
        "libopus",
        str(input_path),
    )
    assert await process.wait() == 0
    storage = LocalStorage(str(tmp_path / "media"))
    original = await storage.save_file("voice.ogg", input_path)
    source, _ = await InboxService(session).register_source(
        SourceCreate(
            telegram_user_id=42,
            telegram_update_id=800,
            type=SourceType.VOICE,
            local_file_path=original,
            mime_type="audio/ogg",
        )
    )
    stt = InspectingSTT()
    service = SourceProcessingService(
        session=session,
        ai_provider=MockAIProvider(),
        storage=storage,
        media_processor=FFmpegMediaProcessor(),
        stt_provider=stt,
        document_processor=DocumentProcessor(),
        image_processor=ImageProcessor(),
        link_processor=NeverLink(),  # type: ignore[arg-type]
        telegram_media=None,
    )

    result = await service.process(source.id)

    assert result.processing_status == SourceStatus.READY
    assert storage.resolve(original).exists()
    assert result.processed_file_path is not None
    assert storage.resolve(result.processed_file_path).exists()
    assert stt.received_path is not None
    assert not stt.received_path.exists()
