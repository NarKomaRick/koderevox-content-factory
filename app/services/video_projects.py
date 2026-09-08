import hashlib
import json
import time
import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider
from app.core.config import Settings
from app.models import (
    ContentDraft,
    ContentIdea,
    Project,
    SourceItem,
    ThumbnailProject,
    VideoProject,
)
from app.models.enums import SourceStatus, SourceType, SubtitlePreset, VideoProjectStatus
from app.schemas.video import (
    EditClip,
    EditPlan,
    ManualClipRequest,
    VideoConcept,
    VideoProjectCreate,
)
from app.services.clip_selector import ClipSelector, LLMClipSelector
from app.services.edit_plan import EditPlanValidator, normalize_phrase
from app.services.errors import InvalidStateError, NotFoundError

VIDEO_SOURCE_TYPES = {SourceType.VIDEO, SourceType.VIDEO_NOTE}


class VideoProjectService:
    def __init__(
        self,
        session: AsyncSession,
        ai_provider: AIProvider,
        settings: Settings,
        clip_selector: ClipSelector | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.clip_selector = clip_selector or LLMClipSelector(ai_provider)
        self.validator = EditPlanValidator(
            minimum_duration=settings.video_min_duration,
            maximum_duration=settings.video_max_duration,
        )

    async def list(self) -> Sequence[VideoProject]:
        return (
            await self.session.scalars(
                select(VideoProject).order_by(VideoProject.created_at.desc())
            )
        ).all()

    async def get(self, video_project_id: uuid.UUID) -> VideoProject:
        project = await self.session.get(VideoProject, video_project_id)
        if project is None:
            raise NotFoundError("VideoProject not found")
        return project

    async def create_from_source(
        self, source_id: uuid.UUID, data: VideoProjectCreate
    ) -> VideoProject:
        source = await self._renderable_source(source_id)
        draft = None
        if data.content_draft_id:
            draft = await self.session.get(ContentDraft, data.content_draft_id)
            if draft is None:
                raise NotFoundError("ContentDraft not found")
            idea = await self.session.get(ContentIdea, draft.idea_id)
            if idea is None or idea.project_id != source.project_id:
                raise InvalidStateError("ContentDraft belongs to another project")
            if idea.source_item_id is not None and idea.source_item_id != source.id:
                raise InvalidStateError("ContentDraft belongs to another source")
        project = VideoProject(
            project_id=source.project_id,
            source_item_id=source.id,
            content_draft_id=data.content_draft_id,
            status=VideoProjectStatus.ANALYZING,
            target_duration=data.target_duration,
            aspect_ratio="9:16",
            subtitle_style={"preset": SubtitlePreset.TECH.value},
            render_settings=self._default_render_settings(),
        )
        self.session.add(project)
        await self.session.commit()
        await self.session.refresh(project)
        return await self.regenerate_concepts(project.id)

    async def regenerate_concepts(self, video_project_id: uuid.UUID) -> VideoProject:
        project = await self.get(video_project_id)
        source = await self._renderable_source(project.source_item_id)
        draft = None
        if project.content_draft_id:
            draft = await self.session.get(ContentDraft, project.content_draft_id)
            if draft is None:
                raise NotFoundError("ContentDraft not found")
        project.status = VideoProjectStatus.ANALYZING
        project.render_error = None
        await self.session.commit()
        started = time.monotonic()
        try:
            brand = await self._project(source.project_id)
            concepts = await self.clip_selector.concepts(source, brand, draft)
            project.concepts = [item.model_dump(mode="json") for item in concepts.concepts]
            project.selected_concept = None
            project.edit_plan = {}
            project.source_start = None
            project.source_end = None
            project.preview_path = None
            project.final_path = None
            project.render_fingerprint = None
            project.render_task_id = None
            project.status = VideoProjectStatus.DRAFT
            project.metrics = {
                **project.metrics,
                "analysis_duration": round(time.monotonic() - started, 3),
            }
            await self.session.commit()
            await self.session.refresh(project)
            return project
        except Exception as exc:
            await self.session.rollback()
            failed = await self.get(video_project_id)
            failed.status = VideoProjectStatus.FAILED
            failed.render_error = f"Analysis failed: {type(exc).__name__}"
            await self.session.commit()
            raise

    async def generate_edit_plan(
        self,
        video_project_id: uuid.UUID,
        concept_index: int,
        instruction: str | None = None,
    ) -> VideoProject:
        video_project = await self.get(video_project_id)
        source = await self._renderable_source(video_project.source_item_id)
        if concept_index >= len(video_project.concepts):
            raise InvalidStateError("Selected video concept does not exist")
        concept = VideoConcept.model_validate(video_project.concepts[concept_index])
        current = (
            EditPlan.model_validate(video_project.edit_plan) if video_project.edit_plan else None
        )
        brand = await self._project(source.project_id)
        video_project.status = VideoProjectStatus.ANALYZING
        await self.session.commit()
        try:
            selected = await self.clip_selector.edit_plan(
                source,
                brand,
                concept,
                self.validator,
                current_plan=current,
                instruction=instruction,
            )
        except InvalidStateError as exc:
            video_project.status = VideoProjectStatus.FAILED
            video_project.render_error = str(exc)
            await self.session.commit()
            raise
        self._apply_plan(video_project, selected.plan, concept_index)
        source.processing_status = SourceStatus.USED
        video_project.metrics = {
            **video_project.metrics,
            "edit_plan_attempts": selected.attempts,
            "number_of_clips": len(selected.plan.clips),
        }
        await self.session.commit()
        await self.session.refresh(video_project)
        return video_project

    async def create_manual(self, source_id: uuid.UUID, data: ManualClipRequest) -> VideoProject:
        source = await self._renderable_source(source_id)
        segment_ids = self.validator.segment_ids_for_range(
            data.source_start, data.source_end, source.transcript_segments
        )
        plan = EditPlan(
            clips=[
                EditClip(
                    source_start=data.source_start,
                    source_end=data.source_end,
                    source_segment_ids=segment_ids,
                    purpose="main",
                )
            ],
            hook_text=data.hook_text or source.topic or "Выбранный фрагмент",
            recommended_duration=data.source_end - data.source_start,
            reasoning_summary="Диапазон вручную выбран пользователем.",
            framing=data.framing,
            pace="medium",
        )
        plan = self.validator.validate(
            plan,
            source_duration=float(source.duration_seconds or 0),
            transcript_segments=source.transcript_segments,
        )
        project = VideoProject(
            project_id=source.project_id,
            source_item_id=source.id,
            status=VideoProjectStatus.READY_TO_RENDER,
            target_duration=plan.recommended_duration,
            source_start=data.source_start,
            source_end=data.source_end,
            concepts=[],
            edit_plan=plan.model_dump(mode="json"),
            subtitle_style={"preset": SubtitlePreset.TECH.value},
            render_settings=self._default_render_settings(),
            metrics={"number_of_clips": 1, "manual_clip": True},
        )
        project.render_fingerprint = self.fingerprint(project)
        self.session.add(project)
        source.processing_status = SourceStatus.USED
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def replace_edit_plan(
        self, video_project_id: uuid.UUID, edit_plan: EditPlan
    ) -> VideoProject:
        video_project = await self.get(video_project_id)
        source = await self._renderable_source(video_project.source_item_id)
        plan = self.validator.validate(
            edit_plan,
            source_duration=float(source.duration_seconds or 0),
            transcript_segments=source.transcript_segments,
        )
        self._apply_plan(video_project, plan, video_project.selected_concept)
        await self.session.commit()
        await self.session.refresh(video_project)
        return video_project

    async def update_style(
        self, video_project_id: uuid.UUID, preset: SubtitlePreset
    ) -> VideoProject:
        video_project = await self.get(video_project_id)
        video_project.subtitle_style = {**video_project.subtitle_style, "preset": preset.value}
        if video_project.edit_plan:
            video_project.status = VideoProjectStatus.READY_TO_RENDER
        video_project.render_fingerprint = self.fingerprint(video_project)
        await self.session.commit()
        await self.session.refresh(video_project)
        return video_project

    async def update_transcript_overrides(
        self, video_project_id: uuid.UUID, replacements: dict[str, str]
    ) -> VideoProject:
        video_project = await self.get(video_project_id)
        source = await self._renderable_source(video_project.source_item_id)
        transcript = normalize_phrase(source.transcript or "")
        for old in replacements:
            if normalize_phrase(old) not in transcript:
                raise InvalidStateError(f"Phrase is not present in transcript: {old}")
        video_project.transcript_overrides = {
            **video_project.transcript_overrides,
            **replacements,
        }
        video_project.status = VideoProjectStatus.READY_TO_RENDER
        video_project.render_fingerprint = self.fingerprint(video_project)
        await self.session.commit()
        await self.session.refresh(video_project)
        return video_project

    async def approve(self, video_project_id: uuid.UUID) -> VideoProject:
        video_project = await self.get(video_project_id)
        if video_project.status != VideoProjectStatus.RENDERED or not video_project.final_path:
            raise InvalidStateError("Only a successfully rendered video can be approved")
        video_project.status = VideoProjectStatus.APPROVED
        await self.session.commit()
        await self.session.refresh(video_project)
        return video_project

    async def archive(self, video_project_id: uuid.UUID) -> VideoProject:
        video_project = await self.get(video_project_id)
        video_project.status = VideoProjectStatus.ARCHIVED
        await self.session.commit()
        await self.session.refresh(video_project)
        return video_project

    async def approved_package(self, video_project_id: uuid.UUID) -> dict[str, object]:
        video_project = await self.get(video_project_id)
        if video_project.status != VideoProjectStatus.APPROVED or not video_project.final_path:
            raise InvalidStateError("Video must be approved before packaging")
        draft = (
            await self.session.get(ContentDraft, video_project.content_draft_id)
            if video_project.content_draft_id
            else None
        )
        thumbnail = (
            await self.session.get(ThumbnailProject, video_project.selected_thumbnail_id)
            if video_project.selected_thumbnail_id
            else None
        )
        return {
            "video_project_id": video_project.id,
            "video_path": video_project.final_path,
            "thumbnail_path": thumbnail.output_path if thumbnail else None,
            "title": draft.title if draft else str(video_project.edit_plan.get("hook_text", "")),
            "caption": draft.caption if draft else "",
            "description": draft.description if draft else "",
            "platform_adaptations": {},
            "project_id": video_project.project_id,
            "publishing_metadata": {"status": "ready", "phase": 4},
        }

    async def request_cancel(self, video_project_id: uuid.UUID) -> VideoProject:
        video_project = await self.get(video_project_id)
        if video_project.status == VideoProjectStatus.RENDERING:
            video_project.status = VideoProjectStatus.CANCEL_REQUESTED
            await self.session.commit()
        return video_project

    async def prepare_render(
        self, video_project_id: uuid.UUID, *, force: bool = False
    ) -> tuple[VideoProject, bool]:
        video_project = await self.get(video_project_id)
        if not video_project.edit_plan:
            raise InvalidStateError("Generate an edit plan before rendering")
        if video_project.status == VideoProjectStatus.RENDERING:
            return video_project, False
        if video_project.status == VideoProjectStatus.RENDERED and not force:
            return video_project, False
        if video_project.status in {
            VideoProjectStatus.ARCHIVED,
            VideoProjectStatus.CANCEL_REQUESTED,
        }:
            raise InvalidStateError("Video project cannot be rendered in its current state")
        video_project.status = VideoProjectStatus.READY_TO_RENDER
        video_project.render_error = None
        video_project.render_fingerprint = self.fingerprint(video_project)
        await self.session.commit()
        await self.session.refresh(video_project)
        return video_project, True

    async def set_render_task_id(self, video_project_id: uuid.UUID, task_id: str) -> VideoProject:
        video_project = await self.get(video_project_id)
        video_project.render_task_id = task_id
        await self.session.commit()
        await self.session.refresh(video_project)
        return video_project

    def fingerprint(self, video_project: VideoProject) -> str:
        payload = {
            "edit_plan": video_project.edit_plan,
            "subtitle_style": video_project.subtitle_style,
            "render_settings": video_project.render_settings,
            "transcript_overrides": video_project.transcript_overrides,
            "source_item_id": str(video_project.source_item_id),
            "visual_plan": video_project.visual_plan,
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        return hashlib.sha256(encoded).hexdigest()

    def _apply_plan(self, project: VideoProject, plan: EditPlan, concept_index: int | None) -> None:
        project.edit_plan = plan.model_dump(mode="json")
        project.selected_concept = concept_index
        project.source_start = min(clip.source_start for clip in plan.clips)
        project.source_end = max(clip.source_end for clip in plan.clips)
        project.target_duration = plan.recommended_duration
        project.render_error = None
        project.status = VideoProjectStatus.READY_TO_RENDER
        project.render_fingerprint = self.fingerprint(project)

    def _default_render_settings(self) -> dict[str, object]:
        return {
            "width": self.settings.video_width,
            "height": self.settings.video_height,
            "fps": self.settings.video_fps,
            "crf": self.settings.video_crf,
            "preset": self.settings.video_preset,
            "audio_normalization": self.settings.audio_normalization_enabled,
            "noise_reduction": self.settings.audio_noise_reduction_enabled,
            "remove_pauses": self.settings.pause_removal_enabled,
            "hook_overlay": self.settings.hook_overlay_enabled,
            "safe_margin_top": self.settings.visual_safe_margin_top,
            "safe_margin_bottom": self.settings.visual_safe_margin_bottom,
        }

    async def _renderable_source(self, source_id: uuid.UUID) -> SourceItem:
        source = await self.session.get(SourceItem, source_id)
        if source is None:
            raise NotFoundError("SourceItem not found")
        if source.type not in VIDEO_SOURCE_TYPES:
            raise InvalidStateError("Video projects require a video or video note source")
        if not source.local_file_path:
            raise InvalidStateError("Video source file is not available")
        if not source.transcript or not source.transcript_segments:
            raise InvalidStateError("Video source has no timestamped transcript")
        if not source.duration_seconds:
            raise InvalidStateError("Video source duration is unknown")
        return source

    async def _project(self, project_id: uuid.UUID) -> Project:
        project = await self.session.get(Project, project_id)
        if project is None:
            raise NotFoundError("Project not found")
        return project
