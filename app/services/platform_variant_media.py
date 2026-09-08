import hashlib
import json
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PlatformVariant, PublishPackage, VideoProject
from app.models.enums import PublishingPlatform, VideoProjectStatus
from app.services.errors import InvalidStateError, NotFoundError


class PlatformVariantMediaService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def prepare_tiktok_derivative(
        self, variant_id: uuid.UUID
    ) -> tuple[PlatformVariant, VideoProject | None]:
        variant = await self.session.get(PlatformVariant, variant_id)
        if variant is None:
            raise NotFoundError("PlatformVariant not found")
        if variant.platform != PublishingPlatform.TIKTOK:
            raise InvalidStateError("Only TikTok uses clean derivative rendering")
        package = await self.session.get(PublishPackage, variant.publish_package_id)
        if package is None or package.video_project_id is None:
            raise InvalidStateError("PublishPackage has no master VideoProject")
        master = await self.session.get(VideoProject, package.video_project_id)
        if master is None:
            raise NotFoundError("Master VideoProject not found")
        settings = dict(variant.settings)
        if not settings.get("requires_rerender"):
            variant.video_path = package.master_video_path
            await self.session.commit()
            return variant, None
        derivative_id = settings.get("derivative_video_project_id")
        if derivative_id:
            derivative = await self.session.get(VideoProject, uuid.UUID(str(derivative_id)))
            if (
                derivative
                and derivative.final_path
                and derivative.status
                in {
                    VideoProjectStatus.RENDERED,
                    VideoProjectStatus.APPROVED,
                }
            ):
                variant.video_path = derivative.final_path
                settings["requires_rerender"] = False
                variant.settings = settings
                variant.content_hash = self._hash(variant)
                await self.session.commit()
                return variant, None
            return variant, derivative
        render_settings = {
            **master.render_settings,
            **settings.get("render_overrides", {}),
        }
        derivative = VideoProject(
            project_id=master.project_id,
            source_item_id=master.source_item_id,
            content_draft_id=master.content_draft_id,
            format=master.format,
            status=VideoProjectStatus.READY_TO_RENDER,
            target_duration=master.target_duration,
            aspect_ratio=master.aspect_ratio,
            source_start=master.source_start,
            source_end=master.source_end,
            concepts=master.concepts,
            selected_concept=master.selected_concept,
            edit_plan=master.edit_plan,
            visual_plan=master.visual_plan,
            subtitle_style=master.subtitle_style,
            render_settings=render_settings,
            transcript_overrides=master.transcript_overrides,
            metrics={"derivative_of": str(master.id), "platform": "tiktok"},
        )
        derivative.render_fingerprint = self._video_fingerprint(derivative)
        self.session.add(derivative)
        await self.session.flush()
        settings["derivative_video_project_id"] = str(derivative.id)
        variant.settings = settings
        await self.session.commit()
        await self.session.refresh(derivative)
        return variant, derivative

    async def attach_rendered(
        self, variant_id: uuid.UUID, derivative_id: uuid.UUID
    ) -> PlatformVariant:
        variant = await self.session.get(PlatformVariant, variant_id)
        derivative = await self.session.get(VideoProject, derivative_id)
        if variant is None or derivative is None:
            raise NotFoundError("Variant derivative not found")
        if derivative.status != VideoProjectStatus.RENDERED or not derivative.final_path:
            raise InvalidStateError("TikTok derivative render did not complete")
        settings = dict(variant.settings)
        settings["requires_rerender"] = False
        variant.settings = settings
        variant.video_path = derivative.final_path
        variant.revision += 1
        variant.content_hash = self._hash(variant)
        await self.session.commit()
        await self.session.refresh(variant)
        return variant

    @staticmethod
    def _video_fingerprint(video: VideoProject) -> str:
        payload = {
            "edit_plan": video.edit_plan,
            "subtitle_style": video.subtitle_style,
            "render_settings": video.render_settings,
            "transcript_overrides": video.transcript_overrides,
            "source_item_id": str(video.source_item_id),
            "visual_plan": video.visual_plan,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()

    @staticmethod
    def _hash(variant: PlatformVariant) -> str:
        payload = {
            "video_path": variant.video_path,
            "thumbnail_path": variant.thumbnail_path,
            "title": variant.title,
            "caption": variant.caption,
            "description": variant.description,
            "hashtags": variant.hashtags,
            "settings": variant.settings,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
