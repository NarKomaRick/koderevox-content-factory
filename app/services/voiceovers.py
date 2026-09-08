import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ProductionProject, ScriptVersion, SourceItem, VoiceoverTrack
from app.models.enums import ProductionStatus, SourceType, VoiceoverStatus
from app.services.errors import InvalidStateError, NotFoundError
from app.services.script_voice_aligner import ScriptVoiceAligner


class VoiceoverService:
    """Promotes an already-ingested SourceItem to the production audio master."""

    def __init__(self, session: AsyncSession, aligner: ScriptVoiceAligner | None = None) -> None:
        self.session = session
        self.aligner = aligner or ScriptVoiceAligner()

    async def create_from_processed_source(
        self, production_project_id: uuid.UUID, source_item_id: uuid.UUID
    ) -> VoiceoverTrack:
        production = await self.session.get(ProductionProject, production_project_id)
        source = await self.session.get(SourceItem, source_item_id)
        if production is None or source is None:
            raise NotFoundError("ProductionProject or SourceItem not found")
        if source.project_id != production.project_id or source.user_id != production.user_id:
            raise InvalidStateError("Voiceover belongs to another production context")
        if source.type not in {SourceType.VOICE, SourceType.AUDIO, SourceType.VIDEO_NOTE}:
            raise InvalidStateError("Voiceover must be voice, audio or video note")
        if not source.local_file_path or not source.processed_file_path:
            raise InvalidStateError("Voiceover audio has not been normalized")
        if not source.transcript or not source.duration_seconds or not source.transcript_segments:
            raise InvalidStateError("Voiceover STT with timestamps is not ready")
        script = (
            await self.session.get(ScriptVersion, production.approved_script_version_id)
            if production.approved_script_version_id
            else None
        )
        words = self._flatten_words(source.transcript_segments)
        alignment = (
            self.aligner.align(
                script.structured_sections,
                words,
                source.transcript,
                duration=float(source.duration_seconds),
            )
            if script
            else None
        )
        if production.primary_voiceover_id:
            previous = await self.session.get(VoiceoverTrack, production.primary_voiceover_id)
            if previous:
                previous.status = VoiceoverStatus.REPLACED
        track = VoiceoverTrack(
            production_project_id=production.id,
            source_item_id=source.id,
            original_path=source.local_file_path,
            processed_path=source.processed_file_path,
            duration=float(source.duration_seconds),
            language=source.transcript_language,
            transcript=source.transcript,
            segments=source.transcript_segments,
            words=words,
            script_version_id=script.id if script else None,
            alignment=alignment.model_dump(mode="json") if alignment else {},
            alignment_score=alignment.overall_confidence if alignment else None,
            status=VoiceoverStatus.READY,
        )
        self.session.add(track)
        await self.session.flush()
        production.primary_voiceover_id = track.id
        production.target_duration = track.duration
        production.status = ProductionStatus.VOICEOVER_READY
        await self.session.commit()
        await self.session.refresh(track)
        return track

    @staticmethod
    def _flatten_words(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "word": str(word.get("word") or "").strip(),
                "start": float(word["start"]),
                "end": float(word["end"]),
            }
            for segment in segments
            for word in segment.get("words", [])
            if str(word.get("word") or "").strip()
            and word.get("start") is not None
            and word.get("end") is not None
        ]
