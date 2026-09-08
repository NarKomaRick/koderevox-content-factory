import builtins
import hashlib
import json
import tempfile
import time
import uuid
from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import ContentDraft, Project, ThumbnailProject, VideoProject, VisualAsset
from app.models.enums import AssetStatus, ThumbnailPreset, ThumbnailStatus
from app.schemas.thumbnails import ThumbnailConcept
from app.services.errors import InvalidStateError, NotFoundError
from app.services.graphics import ThumbnailRenderer
from app.services.video_editor import FFmpegVideoEditor
from app.storage.base import Storage


class FrameExtractor:
    def __init__(self, editor: FFmpegVideoEditor | None = None) -> None:
        self.editor = editor or FFmpegVideoEditor()

    async def candidates(self, video_path: Path, destination: Path, duration: float) -> list[Path]:
        return await self.editor.extract_preview_frames(video_path, destination, duration)


class ThumbnailService:
    def __init__(
        self,
        session: AsyncSession,
        storage: Storage,
        settings: Settings,
        renderer: ThumbnailRenderer | None = None,
    ) -> None:
        self.session = session
        self.storage = storage
        self.settings = settings
        self.renderer = renderer or ThumbnailRenderer()

    async def list(self, video_project_id: uuid.UUID) -> Sequence[ThumbnailProject]:
        return (
            await self.session.scalars(
                select(ThumbnailProject)
                .where(ThumbnailProject.video_project_id == video_project_id)
                .order_by(ThumbnailProject.created_at)
            )
        ).all()

    async def get(self, thumbnail_id: uuid.UUID) -> ThumbnailProject:
        thumbnail = await self.session.get(ThumbnailProject, thumbnail_id)
        if thumbnail is None:
            raise NotFoundError("ThumbnailProject not found")
        return thumbnail

    async def generate(
        self, video_project_id: uuid.UUID, custom_headline: str | None = None
    ) -> Sequence[ThumbnailProject]:
        video = await self.session.get(VideoProject, video_project_id)
        if video is None:
            raise NotFoundError("VideoProject not found")
        project = await self.session.get(Project, video.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        headlines = await self._headlines(video, custom_headline)
        subject = await self._subject(video)
        frame_paths = [str(path) for path in video.metrics.get("preview_frames", [])]
        results: builtins.list[ThumbnailProject] = []
        for index, headline in enumerate(headlines):
            frame_path = frame_paths[index % len(frame_paths)] if frame_paths else None
            concept = ThumbnailConcept(
                headline=headline,
                subject_asset_id=subject.id if subject else None,
                frame_path=frame_path,
                composition="subject_right" if subject else "type_only",
                emphasis_words=headline.split()[-2:],
                preset=ThumbnailPreset.TECH_DARK,
            )
            fingerprint = hashlib.sha256(
                json.dumps(concept.model_dump(mode="json"), sort_keys=True).encode()
            ).hexdigest()
            existing = await self.session.scalar(
                select(ThumbnailProject).where(
                    ThumbnailProject.video_project_id == video.id,
                    ThumbnailProject.render_fingerprint == fingerprint,
                )
            )
            cached = (
                existing
                and existing.output_path
                and self.storage.resolve(existing.output_path).is_file()
            )
            if cached:
                assert existing is not None
                results.append(existing)
                continue
            thumbnail = existing or ThumbnailProject(
                project_id=video.project_id,
                video_project_id=video.id,
                status=ThumbnailStatus.RENDERING,
                concept=concept.model_dump(mode="json"),
                render_settings={
                    "width": self.settings.thumbnail_width,
                    "height": self.settings.thumbnail_height,
                },
                render_fingerprint=fingerprint,
            )
            self.session.add(thumbnail)
            await self.session.flush()
            started = time.monotonic()
            with tempfile.TemporaryDirectory(prefix="thumbnail-") as temp_dir:
                output = Path(temp_dir) / f"{thumbnail.id}.jpg"
                subject_path = (
                    self.storage.resolve(subject.processed_path or subject.original_path)
                    if subject
                    else self.storage.resolve(frame_path)
                    if frame_path
                    else None
                )
                logo_raw = project.brand_preset.get("logo_path")
                logo_path = self.storage.resolve(logo_raw) if logo_raw else None
                await self.renderer.render(
                    concept,
                    output,
                    subject_path=subject_path,
                    width=self.settings.thumbnail_width,
                    height=self.settings.thumbnail_height,
                    font_path=project.brand_preset.get("font_path", self.settings.video_font_path),
                    logo_path=logo_path,
                )
                thumbnail.output_path = await self.storage.save_file(output.name, output, "preview")
            thumbnail.status = ThumbnailStatus.RENDERED
            thumbnail.metrics = {"thumbnail_render_duration": round(time.monotonic() - started, 3)}
            results.append(thumbnail)
        await self.session.commit()
        return results

    async def select(self, thumbnail_id: uuid.UUID) -> ThumbnailProject:
        thumbnail = await self.get(thumbnail_id)
        if thumbnail.status not in {ThumbnailStatus.RENDERED, ThumbnailStatus.SELECTED}:
            raise InvalidStateError("Thumbnail has not rendered successfully")
        siblings = await self.list(thumbnail.video_project_id)
        for item in siblings:
            if item.status == ThumbnailStatus.SELECTED:
                item.status = ThumbnailStatus.RENDERED
        thumbnail.status = ThumbnailStatus.SELECTED
        video = await self.session.get(VideoProject, thumbnail.video_project_id)
        assert video is not None
        video.selected_thumbnail_id = thumbnail.id
        await self.session.commit()
        await self.session.refresh(thumbnail)
        return thumbnail

    async def _headlines(self, video: VideoProject, custom: str | None) -> builtins.list[str]:
        if custom:
            return [custom]
        title = "ТЕХНИЧЕСКИЙ РАЗБОР"
        if video.content_draft_id:
            draft = await self.session.get(ContentDraft, video.content_draft_id)
            if draft:
                title = draft.title
        elif video.edit_plan:
            title = str(video.edit_plan.get("hook_text") or title)
        words = title.replace("?", "").split()
        compact = " ".join(words[:6])
        subject = " ".join(words[-3:]) if len(words) > 3 else compact
        return [compact, f"{subject}?", f"РАЗБОР: {' '.join(words[:3])}"]

    async def _subject(self, video: VideoProject) -> VisualAsset | None:
        return await self.session.scalar(
            select(VisualAsset)
            .where(
                VisualAsset.project_id == video.project_id,
                VisualAsset.status == AssetStatus.READY,
                VisualAsset.mime_type.in_(["image/jpeg", "image/png", "image/webp"]),
            )
            .order_by(VisualAsset.favorite.desc(), VisualAsset.created_at.desc())
        )
