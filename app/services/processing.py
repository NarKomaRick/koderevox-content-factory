import inspect
import tempfile
import uuid
from datetime import UTC, datetime
from pathlib import Path

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider
from app.ai.openai_compatible import AIProviderError
from app.ai.prompts.content_intelligence import build_content_intelligence_prompt
from app.ai.prompts.system import build_system_prompt
from app.models import Project, SourceItem, SourceNote
from app.models.enums import ProcessingStage, SourceStatus, SourceType
from app.schemas.ai import ContentIntelligence
from app.services.assets import AssetService
from app.services.document_processor import DocumentProcessor
from app.services.errors import NotFoundError, PermanentProcessingError, TemporaryProcessingError
from app.services.image_processor import ImageProcessor
from app.services.interfaces import SpeechToTextProvider
from app.services.link_processor import LinkProcessor
from app.services.media import FFmpegMediaProcessor
from app.services.telegram_media import TelegramMediaService
from app.storage.base import Storage

logger = structlog.get_logger()

MEDIA_TYPES = {
    SourceType.VOICE,
    SourceType.AUDIO,
    SourceType.VIDEO,
    SourceType.VIDEO_NOTE,
    SourceType.IMAGE,
    SourceType.DOCUMENT,
}
AUDIO_VIDEO_TYPES = {
    SourceType.VOICE,
    SourceType.AUDIO,
    SourceType.VIDEO,
    SourceType.VIDEO_NOTE,
}


class SourceProcessingService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        ai_provider: AIProvider,
        storage: Storage,
        media_processor: FFmpegMediaProcessor,
        stt_provider: SpeechToTextProvider,
        document_processor: DocumentProcessor,
        image_processor: ImageProcessor,
        link_processor: LinkProcessor,
        telegram_media: TelegramMediaService | None,
        asset_service: AssetService | None = None,
    ) -> None:
        self.session = session
        self.ai = ai_provider
        self.storage = storage
        self.media = media_processor
        self.stt = stt_provider
        self.documents = document_processor
        self.images = image_processor
        self.links = link_processor
        self.telegram_media = telegram_media
        self.assets = asset_service

    async def process(self, source_id: uuid.UUID) -> SourceItem:
        if not await self._claim(source_id):
            return await self._get_source(source_id)
        try:
            source = await self._get_source(source_id)
            if source.type in MEDIA_TYPES:
                await self._ensure_downloaded(source)
            content = await self._extract_content(source)
            if content.strip():
                await self._enrich(source, content)
            else:
                await self._fallback_without_text(source)
            source.processing_status = SourceStatus.READY
            source.processing_stage = ProcessingStage.READY
            source.processing_error = None
            source.completed_at = datetime.now(UTC)
            await self.session.commit()
            if self.assets is not None:
                try:
                    await self.assets.ingest_source(source)
                except Exception as exc:
                    await self.session.rollback()
                    await logger.awarning(
                        "source_asset_indexing_failed",
                        source_id=str(source.id),
                        error_type=type(exc).__name__,
                    )
            await self.session.refresh(source)
            await logger.ainfo("source_processing_completed", source_id=str(source.id))
            return source
        except Exception as exc:
            await self.session.rollback()
            source = await self._get_source(source_id)
            source.processing_status = SourceStatus.FAILED
            source.processing_stage = ProcessingStage.FAILED
            source.processing_error = f"{type(exc).__name__}: {str(exc)[:900]}"
            await self.session.commit()
            await logger.aexception(
                "source_processing_failed",
                source_id=str(source_id),
                error_type=type(exc).__name__,
            )
            raise

    async def aclose(self) -> None:
        for dependency in (self.links, self.telegram_media, self.ai):
            close = getattr(dependency, "aclose", None)
            if close is not None:
                await close()

    async def process_voice_note(self, note_id: uuid.UUID) -> SourceItem:
        note = await self.session.get(SourceNote, note_id)
        if note is None:
            raise NotFoundError("SourceNote not found")
        source = await self._get_source(note.source_item_id)
        if note.transcript:
            if source.processing_status in {SourceStatus.READY, SourceStatus.USED}:
                return source
            return await self.process(source.id)
        if not note.telegram_file_id or self.telegram_media is None:
            raise PermanentProcessingError("Voice note has no downloadable media")
        try:
            if not note.local_file_path:
                path, metadata = await self.telegram_media.download(
                    file_id=note.telegram_file_id,
                    original_filename="context.ogg",
                    mime_type=note.mime_type or "audio/ogg",
                    declared_size=note.file_size,
                )
                note.local_file_path = path
                note.note_metadata = {**note.note_metadata, **metadata}
                await self.session.commit()
            local_path = self.storage.resolve(note.local_file_path)
            with tempfile.TemporaryDirectory(prefix="content-factory-note-") as temp_dir:
                normalized = Path(temp_dir) / "context.wav"
                await self.media.normalize_audio(local_path, normalized)
                transcription = await self._transcribe(normalized, source.project_id)
            note.transcript = transcription.text
            note.note_metadata = {
                **note.note_metadata,
                "language": transcription.language,
                "duration": transcription.duration,
                "segments": [item.model_dump() for item in transcription.segments],
            }
            source.processing_status = SourceStatus.NEW
            source.processing_stage = ProcessingStage.RECEIVED
            await self.session.commit()
            return await self.process(source.id)
        except Exception as exc:
            await self.session.rollback()
            failed_source = await self._get_source(note.source_item_id)
            failed_source.processing_status = SourceStatus.FAILED
            failed_source.processing_stage = ProcessingStage.FAILED
            failed_source.processing_error = f"Voice context: {type(exc).__name__}"
            await self.session.commit()
            raise

    async def _claim(self, source_id: uuid.UUID) -> bool:
        statement = (
            update(SourceItem)
            .where(
                SourceItem.id == source_id,
                SourceItem.processing_status.in_([SourceStatus.NEW, SourceStatus.FAILED]),
            )
            .values(
                processing_status=SourceStatus.PROCESSING,
                processing_stage=ProcessingStage.RECEIVED,
                processing_error=None,
            )
            .returning(SourceItem.id)
        )
        claimed = (await self.session.execute(statement)).scalar_one_or_none()
        await self.session.commit()
        if claimed:
            await logger.ainfo("source_processing_claimed", source_id=str(source_id))
        return claimed is not None

    async def _ensure_downloaded(self, source: SourceItem) -> None:
        if source.local_file_path:
            await self._stage(source, ProcessingStage.DOWNLOADED)
            return
        if not source.telegram_file_id or self.telegram_media is None:
            raise PermanentProcessingError("No media downloader or Telegram file ID available")
        path, metadata = await self.telegram_media.download(
            file_id=source.telegram_file_id,
            original_filename=source.original_filename,
            mime_type=source.mime_type,
            declared_size=source.file_size,
        )
        source.local_file_path = path
        source.source_metadata = {**source.source_metadata, **metadata}
        if metadata.get("downloaded_size"):
            source.file_size = int(metadata["downloaded_size"])
        await self._stage(source, ProcessingStage.DOWNLOADED)

    async def _extract_content(self, source: SourceItem) -> str:
        if source.type == SourceType.TEXT:
            return source.original_text or ""
        if source.type == SourceType.URL:
            link = await self.links.process(source.original_text or "")
            source.extracted_text = link.main_text
            source.source_metadata = {**source.source_metadata, "link": link.model_dump()}
            await self._stage(source, ProcessingStage.EXTRACTED)
            return self._with_caption(source, link.main_text)
        if not source.local_file_path:
            raise PermanentProcessingError("Media has no local storage path")
        local_path = self.storage.resolve(source.local_file_path)
        if source.type in AUDIO_VIDEO_TYPES:
            return await self._transcribe_media(source, local_path)
        if source.type == SourceType.DOCUMENT:
            document = await self.documents.extract(local_path, source.mime_type)
            source.extracted_text = document.text
            source.source_metadata = {
                **source.source_metadata,
                "document": document.model_dump(),
            }
            await self._stage(source, ProcessingStage.EXTRACTED)
            return self._with_caption(source, document.text)
        if source.type == SourceType.IMAGE:
            metadata = await self.images.metadata(local_path)
            source.source_metadata = {**source.source_metadata, "image": metadata}
            await self._stage(source, ProcessingStage.MEDIA_PREPARED)
            return source.original_text or ""
        raise PermanentProcessingError(f"Unsupported source type: {source.type}")

    async def _transcribe_media(self, source: SourceItem, local_path: Path) -> str:
        probe = await self.media.probe(local_path)
        media_metadata = self.media.useful_metadata(probe)
        source.source_metadata = {**source.source_metadata, "media": media_metadata}
        if media_metadata.get("duration_seconds") is not None:
            source.duration_seconds = float(media_metadata["duration_seconds"])
        await self._stage(source, ProcessingStage.MEDIA_PREPARED)
        with tempfile.TemporaryDirectory(prefix="content-factory-media-") as temp_dir:
            normalized = Path(temp_dir) / "audio.wav"
            await self.media.normalize_audio(local_path, normalized)
            source.processed_file_path = await self.storage.save_file(
                "audio.wav", normalized, "processed"
            )
            result = await self._transcribe(normalized, source.project_id)
        source.transcript = result.text
        source.transcript_language = result.language
        source.transcript_segments = [segment.model_dump() for segment in result.segments]
        if result.duration is not None:
            source.duration_seconds = result.duration
        await self._stage(source, ProcessingStage.TRANSCRIBED)
        return self._with_caption(source, result.text)

    async def _enrich(self, source: SourceItem, content: str) -> None:
        project = await self.session.get(Project, source.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        notes = await self.session.scalars(
            select(SourceNote)
            .where(SourceNote.source_item_id == source.id)
            .order_by(SourceNote.created_at)
        )
        note_text = "\n".join(filter(None, [(note.text or note.transcript) for note in notes]))
        try:
            intelligence = await self.ai.generate_structured(
                system_prompt=build_system_prompt(project),
                user_prompt=build_content_intelligence_prompt(content, note_text),
                response_model=ContentIntelligence,
            )
        except AIProviderError as exc:
            raise TemporaryProcessingError("AI enrichment is temporarily unavailable") from exc
        source.topic = intelligence.topic
        source.summary = intelligence.summary
        source.content_potential_score = intelligence.content_potential_score
        source.content_analysis = intelligence.model_dump(mode="json")
        await self._stage(source, ProcessingStage.ENRICHED)

    async def _fallback_without_text(self, source: SourceItem) -> None:
        if source.type == SourceType.IMAGE:
            source.topic = source.original_filename or "Изображение"
            source.summary = "Изображение сохранено без AI-анализа. Добавьте комментарий."
        elif source.type == SourceType.DOCUMENT:
            source.topic = source.original_filename or "Документ"
            source.summary = "Документ сохранён, но текст извлечь не удалось."
        else:
            source.topic = source.original_filename or "Материал"
            source.summary = "Материал сохранён без извлечённого текста."
        source.content_potential_score = None

    async def _stage(self, source: SourceItem, stage: ProcessingStage) -> None:
        source.processing_stage = stage
        await self.session.commit()
        await logger.ainfo("source_processing_stage", source_id=str(source.id), stage=stage.value)

    async def _get_source(self, source_id: uuid.UUID) -> SourceItem:
        source = await self.session.get(SourceItem, source_id)
        if source is None:
            raise NotFoundError("SourceItem not found")
        return source

    @staticmethod
    def _with_caption(source: SourceItem, content: str) -> str:
        caption = str(source.source_metadata.get("caption") or "").strip()
        return f"{caption}\n\n{content}".strip()

    async def _transcribe(self, path: Path, project_id: uuid.UUID):
        project = await self.session.get(Project, project_id)
        parameters = inspect.signature(self.stt.transcribe).parameters
        if "vocabulary" in parameters:
            return await self.stt.transcribe(
                path, vocabulary=(project.vocabulary if project else [])
            )
        return await self.stt.transcribe(path)
