import asyncio
from pathlib import Path

import pytest

from app.ai.mock import MockAIProvider
from app.models.enums import ProcessingStage, SourceStatus, SourceType
from app.schemas.api import SourceCreate
from app.schemas.processing import TranscriptionResult, TranscriptSegment
from app.services.document_processor import DocumentProcessor
from app.services.errors import PermanentProcessingError
from app.services.image_processor import ImageProcessor
from app.services.inbox import InboxService
from app.services.processing import SourceProcessingService
from app.storage.local import LocalStorage


class FakeMediaProcessor:
    async def probe(self, _source: Path) -> dict:
        return {
            "format": {"duration": "12.5"},
            "streams": [
                {
                    "codec_type": "video",
                    "width": 1080,
                    "height": 1920,
                    "avg_frame_rate": "30/1",
                    "codec_name": "h264",
                },
                {"codec_type": "audio", "codec_name": "opus", "sample_rate": "48000"},
            ],
        }

    def useful_metadata(self, probe: dict) -> dict:
        from app.services.media import FFmpegMediaProcessor

        return FFmpegMediaProcessor.useful_metadata(probe)

    async def normalize_audio(self, _source: Path, destination: Path) -> Path:
        await asyncio.to_thread(destination.write_bytes, b"normalized audio")
        return destination


class FakeSTT:
    def __init__(self) -> None:
        self.calls = 0

    async def transcribe(self, _media_path: Path) -> TranscriptionResult:
        self.calls += 1
        return TranscriptionResult(
            text=(
                "Сегодня обнаружили, что приложение повторно отправляло запрос при возврате "
                "на экран, и 1С получала две записи."
            ),
            language="ru",
            duration=12.5,
            segments=[
                TranscriptSegment(start=0, end=5.2, text="Сегодня обнаружили проблему."),
                TranscriptSegment(start=5.2, end=12.5, text="1С получала две записи."),
            ],
        )


class FailingSTT:
    async def transcribe(self, _media_path: Path) -> TranscriptionResult:
        raise PermanentProcessingError("Unsupported audio")


class UnusedLinkProcessor:
    async def process(self, _url: str):
        raise AssertionError("Link processor should not be called")


class CountingAI(MockAIProvider):
    def __init__(self) -> None:
        self.calls = 0

    async def generate_structured(self, **kwargs):
        self.calls += 1
        return await super().generate_structured(**kwargs)


def processing_service(session, storage, stt, ai=None) -> SourceProcessingService:
    return SourceProcessingService(
        session=session,
        ai_provider=ai or MockAIProvider(),
        storage=storage,
        media_processor=FakeMediaProcessor(),  # type: ignore[arg-type]
        stt_provider=stt,
        document_processor=DocumentProcessor(),
        image_processor=ImageProcessor(),
        link_processor=UnusedLinkProcessor(),  # type: ignore[arg-type]
        telegram_media=None,
    )


@pytest.mark.parametrize("source_type", [SourceType.VOICE, SourceType.VIDEO])
async def test_audio_video_pipeline_preserves_segments_and_metadata(
    session, tmp_path, source_type
) -> None:
    storage = LocalStorage(str(tmp_path))
    original_path = await storage.save("source.ogg", b"media")
    source, _ = await InboxService(session).register_source(
        SourceCreate(
            telegram_user_id=42,
            type=source_type,
            local_file_path=original_path,
            telegram_update_id=10 if source_type == SourceType.VOICE else 11,
        )
    )
    stt = FakeSTT()

    result = await processing_service(session, storage, stt).process(source.id)

    assert result.processing_status == SourceStatus.READY
    assert result.processing_stage == ProcessingStage.READY
    assert result.transcript_language == "ru"
    assert len(result.transcript_segments) == 2
    assert result.processed_file_path is not None
    assert storage.resolve(result.processed_file_path).exists()
    assert result.source_metadata["media"]["width"] == 1080
    assert result.content_potential_score == 82


async def test_processing_failure_records_stage_and_error(session, tmp_path) -> None:
    storage = LocalStorage(str(tmp_path))
    path = await storage.save("bad.ogg", b"bad")
    source, _ = await InboxService(session).register_source(
        SourceCreate(
            telegram_user_id=42,
            type=SourceType.VOICE,
            local_file_path=path,
            telegram_update_id=20,
        )
    )

    with pytest.raises(PermanentProcessingError):
        await processing_service(session, storage, FailingSTT()).process(source.id)

    await session.refresh(source)
    assert source.processing_status == SourceStatus.FAILED
    assert source.processing_stage == ProcessingStage.FAILED
    assert "PermanentProcessingError" in (source.processing_error or "")


async def test_duplicate_task_execution_is_idempotent(session, tmp_path) -> None:
    storage = LocalStorage(str(tmp_path))
    source, _ = await InboxService(session).register_source(
        SourceCreate(
            telegram_user_id=42,
            type=SourceType.TEXT,
            original_text="Баг с двойными REST-запросами",
            telegram_update_id=30,
        )
    )
    ai = CountingAI()
    service = processing_service(session, storage, FakeSTT(), ai)

    await service.process(source.id)
    await service.process(source.id)

    assert ai.calls == 1
