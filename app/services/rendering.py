import asyncio
import shutil
import tempfile
import time
import uuid
from pathlib import Path

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import Project, SourceItem, VideoProject
from app.models.enums import SubtitlePreset, VideoProjectStatus
from app.schemas.video import EditPlan
from app.services.edit_plan import EditPlanValidator
from app.services.errors import InvalidStateError, NotFoundError
from app.services.media import FFmpegMediaProcessor, MediaProcessingError
from app.services.pause import FFmpegPauseDetector, TimeRange, clips_without_long_pauses
from app.services.subtitles import SubtitleService
from app.services.video_editor import FFmpegVideoEditor, RenderResult, VideoEditor
from app.storage.base import Storage

logger = structlog.get_logger()


class RenderCancelledError(InvalidStateError):
    pass


class VideoRenderService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        storage: Storage,
        settings: Settings,
        editor: VideoEditor | None = None,
        media: FFmpegMediaProcessor | None = None,
        subtitles: SubtitleService | None = None,
        pause_detector: FFmpegPauseDetector | None = None,
    ) -> None:
        self.session = session
        self.storage = storage
        self.settings = settings
        self.editor = editor or FFmpegVideoEditor(font_path=settings.video_font_path)
        self.media = media or FFmpegMediaProcessor()
        self.subtitles = subtitles or SubtitleService()
        self.pause_detector = pause_detector or FFmpegPauseDetector(
            settings.pause_min_duration, settings.pause_noise_db
        )
        self.validator = EditPlanValidator(
            minimum_duration=settings.video_min_duration,
            maximum_duration=settings.video_max_duration,
        )

    async def render(self, video_project_id: uuid.UUID, expected_fingerprint: str) -> VideoProject:
        video_project = await self._get(video_project_id)
        if (
            video_project.status in {VideoProjectStatus.RENDERED, VideoProjectStatus.APPROVED}
            and video_project.render_fingerprint == expected_fingerprint
            and video_project.final_path
            and self.storage.resolve(video_project.final_path).exists()
        ):
            return video_project
        if not await self._claim(video_project_id, expected_fingerprint):
            return await self._get(video_project_id)
        workspace_root = Path(self.settings.render_temp_root)
        await asyncio.to_thread(workspace_root.mkdir, parents=True, exist_ok=True)
        workspace = Path(tempfile.mkdtemp(prefix=f"{video_project_id}-", dir=workspace_root))
        started = time.monotonic()
        try:
            video_project = await self._get(video_project_id)
            source = await self.session.get(SourceItem, video_project.source_item_id)
            brand = await self.session.get(Project, video_project.project_id)
            if source is None or brand is None:
                raise NotFoundError("Video project dependencies not found")
            if not source.local_file_path:
                raise InvalidStateError("Source video is missing")
            source_path = self.storage.resolve(source.local_file_path)
            if not source_path.is_file():
                raise InvalidStateError("Source video file does not exist")
            probe = await self.media.probe(source_path)
            media_metadata = self.media.useful_metadata(probe)
            if not media_metadata.get("video_codec") or not media_metadata.get("audio_codec"):
                raise InvalidStateError("Source must contain both video and audio")
            await self._log_stage(video_project_id, "source_validated")
            plan = self.validator.validate(
                EditPlan.model_validate(video_project.edit_plan),
                source_duration=float(source.duration_seconds or 0),
                transcript_segments=source.transcript_segments,
            )
            await self._log_stage(video_project_id, "edit_plan_validated")
            if await self._cancel_requested(video_project_id):
                raise RenderCancelledError("Render cancelled")
            clips = [TimeRange(clip.source_start, clip.source_end) for clip in plan.clips]
            if video_project.render_settings.get("remove_pauses", True):
                pauses = await self.pause_detector.detect(source_path)
                shortened = clips_without_long_pauses(
                    plan.clips,
                    pauses,
                    keep_padding=self.settings.pause_keep_padding,
                    minimum_pause=self.settings.pause_min_duration,
                )
                if sum(item.duration for item in shortened) >= self.settings.video_min_duration:
                    clips = shortened
            await self._log_stage(
                video_project_id,
                "pause_cleanup_ready",
                clip_count=len(clips),
            )
            preset = SubtitlePreset(
                video_project.subtitle_style.get("preset", SubtitlePreset.TECH.value)
            )
            cues = self.subtitles.create_cues(
                source.transcript_segments,
                clips,
                preset=preset,
                vocabulary=brand.vocabulary,
                overrides=video_project.transcript_overrides,
            )
            output_duration = sum(clip.duration for clip in clips)
            if not cues or any(cue.end > output_duration + 0.25 for cue in cues):
                raise InvalidStateError("Subtitle timings do not fit the output timeline")
            subtitle_path = self.subtitles.write_ass(
                workspace / "subtitles.ass",
                cues,
                preset=preset,
                width=int(video_project.render_settings["width"]),
                height=int(video_project.render_settings["height"]),
                emphasis=[item.text for item in plan.emphasis],
            )
            await self._log_stage(
                video_project_id,
                "subtitles_ready",
                cue_count=len(cues),
                preset=preset.value,
            )
            output = workspace / "short.mp4"
            result = await self.editor.render(
                source=source_path,
                destination=output,
                clips=clips,
                plan=plan,
                subtitle_file=subtitle_path,
                settings=video_project.render_settings,
            )
            if await self._cancel_requested(video_project_id):
                raise RenderCancelledError("Render cancelled")
            final_path = await self.storage.save_file(
                f"{video_project.id}.mp4", result.output_path, "render"
            )
            await self._log_stage(video_project_id, "final_stored", path=final_path)
            frames = await self._preview_frames(result, workspace, video_project.id)
            await self._log_stage(
                video_project_id,
                "preview_frames_stored",
                frame_count=len(frames),
            )
            video_project = await self._get(video_project_id)
            video_project.final_path = final_path
            video_project.preview_path = final_path
            video_project.status = VideoProjectStatus.RENDERED
            video_project.render_error = None
            video_project.metrics = {
                **video_project.metrics,
                "render_duration": round(time.monotonic() - started, 3),
                "source_duration": source.duration_seconds,
                "output_duration": result.duration,
                "output_size": result.size_bytes,
                "number_of_clips": len(clips),
                "preview_frames": frames,
                "source_width": media_metadata.get("width"),
                "source_height": media_metadata.get("height"),
                "upscaled": bool(
                    (media_metadata.get("width") or 0) < int(video_project.render_settings["width"])
                    or (media_metadata.get("height") or 0)
                    < int(video_project.render_settings["height"])
                ),
            }
            await self.session.commit()
            await self.session.refresh(video_project)
            return video_project
        except Exception as exc:
            await self.session.rollback()
            failed = await self._get(video_project_id)
            failed.status = (
                VideoProjectStatus.DRAFT
                if isinstance(exc, RenderCancelledError)
                else VideoProjectStatus.FAILED
            )
            failed.render_error = self._sanitized_error(exc)
            await self.session.commit()
            await logger.aexception(
                "video_render_failed",
                video_project_id=str(video_project_id),
                error_type=type(exc).__name__,
            )
            raise
        finally:
            await asyncio.to_thread(shutil.rmtree, workspace, True)

    async def _preview_frames(
        self, result: RenderResult, workspace: Path, video_project_id: uuid.UUID
    ) -> list[str]:
        extractor = getattr(self.editor, "extract_preview_frames", None)
        if extractor is None:
            return []
        local_frames = await extractor(result.output_path, workspace / "frames", result.duration)
        return [
            await self.storage.save_file(f"{video_project_id}-{index}.jpg", frame, "debug")
            for index, frame in enumerate(local_frames)
        ]

    async def _claim(self, project_id: uuid.UUID, fingerprint: str) -> bool:
        statement = (
            update(VideoProject)
            .where(
                VideoProject.id == project_id,
                VideoProject.render_fingerprint == fingerprint,
                VideoProject.status.in_(
                    [VideoProjectStatus.READY_TO_RENDER, VideoProjectStatus.FAILED]
                ),
            )
            .values(status=VideoProjectStatus.RENDERING, render_error=None)
            .returning(VideoProject.id)
        )
        claimed = (await self.session.execute(statement)).scalar_one_or_none()
        await self.session.commit()
        return claimed is not None

    async def _get(self, project_id: uuid.UUID) -> VideoProject:
        project = await self.session.get(VideoProject, project_id)
        if project is None:
            raise NotFoundError("VideoProject not found")
        return project

    async def _cancel_requested(self, project_id: uuid.UUID) -> bool:
        status = await self.session.scalar(
            select(VideoProject.status).where(VideoProject.id == project_id)
        )
        return status == VideoProjectStatus.CANCEL_REQUESTED

    @staticmethod
    async def _log_stage(project_id: uuid.UUID, stage: str, **metadata: object) -> None:
        await logger.ainfo(
            "video_render_stage",
            video_project_id=str(project_id),
            stage=stage,
            **metadata,
        )

    @staticmethod
    def _sanitized_error(exc: Exception) -> str:
        if isinstance(exc, (InvalidStateError, NotFoundError)):
            return str(exc)[:500]
        if isinstance(exc, MediaProcessingError):
            return "Video processing failed. See application logs for FFmpeg details."
        return f"Render failed: {type(exc).__name__}"
