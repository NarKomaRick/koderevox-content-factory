import hashlib
import json
import uuid
from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider
from app.models import (
    ContentDraft,
    Project,
    PublishPackage,
    SourceItem,
    ThumbnailProject,
    VideoProject,
)
from app.models.entities import PlatformVariant
from app.models.enums import (
    PublishingPlatform,
    PublishPackageStatus,
    VideoProjectStatus,
)
from app.schemas.publishing import PlatformAdaptationOutput
from app.services.errors import InvalidStateError, NotFoundError
from app.services.platform_profiles import PlatformMediaProfiles


class PlatformAdaptationService:
    def __init__(self, session: AsyncSession, ai: AIProvider) -> None:
        self.session = session
        self.ai = ai
        self.profiles = PlatformMediaProfiles()

    async def prepare_package(
        self,
        video_project_id: uuid.UUID,
        platforms: Sequence[PublishingPlatform],
        *,
        regenerate: bool = False,
    ) -> tuple[PublishPackage, list[PlatformVariant]]:
        video = await self.session.get(VideoProject, video_project_id)
        if video is None:
            raise NotFoundError("VideoProject not found")
        if video.status != VideoProjectStatus.APPROVED or not video.final_path:
            raise InvalidStateError("Only an approved video can become a PublishPackage")
        package = await self.session.scalar(
            select(PublishPackage).where(PublishPackage.video_project_id == video.id)
        )
        draft = (
            await self.session.get(ContentDraft, video.content_draft_id)
            if video.content_draft_id
            else None
        )
        thumbnail = (
            await self.session.get(ThumbnailProject, video.selected_thumbnail_id)
            if video.selected_thumbnail_id
            else None
        )
        if package is None:
            package = PublishPackage(
                project_id=video.project_id,
                content_draft_id=video.content_draft_id,
                video_project_id=video.id,
                thumbnail_project_id=thumbnail.id if thumbnail else None,
                status=PublishPackageStatus.DRAFT,
                master_video_path=video.final_path,
                master_thumbnail_path=thumbnail.output_path if thumbnail else None,
                base_title=(draft.title if draft else str(video.edit_plan.get("hook_text", ""))),
                base_caption=draft.caption if draft else "",
                base_description=draft.description if draft else "",
                package_metadata={
                    "source_render_fingerprint": video.render_fingerprint,
                    "phase": 5,
                },
            )
            self.session.add(package)
            await self.session.flush()
        brand = await self.session.get(Project, video.project_id)
        if brand is None:
            raise NotFoundError("Project not found")
        variants: list[PlatformVariant] = []
        for platform in dict.fromkeys(platforms):
            existing = await self.session.scalar(
                select(PlatformVariant).where(
                    PlatformVariant.publish_package_id == package.id,
                    PlatformVariant.platform == platform,
                )
            )
            if existing is not None and not regenerate:
                variants.append(existing)
                continue
            adaptation = await self._adapt(package, video, draft, platform)
            payload = self._variant_payload(package, video, brand, adaptation, platform)
            if existing is None:
                existing = PlatformVariant(
                    publish_package_id=package.id,
                    platform=platform,
                    revision=1,
                    **payload,
                )
                self.session.add(existing)
            else:
                for name, value in payload.items():
                    setattr(existing, name, value)
                existing.revision += 1
            variants.append(existing)
        await self.session.flush()
        all_variants = list(
            await self.session.scalars(
                select(PlatformVariant).where(PlatformVariant.publish_package_id == package.id)
            )
        )
        captions: dict[str, PublishingPlatform] = {}
        for variant in all_variants:
            normalized = " ".join(variant.caption.lower().split())
            if not normalized:
                continue
            duplicate = captions.get(normalized)
            if duplicate is not None and duplicate != variant.platform:
                await self.session.rollback()
                raise InvalidStateError(
                    f"{duplicate.value} and {variant.platform.value} captions must be distinct"
                )
            captions[normalized] = variant.platform
        package.status = PublishPackageStatus.READY
        await self.session.commit()
        await self.session.refresh(package)
        for variant in variants:
            await self.session.refresh(variant)
        return package, variants

    async def update_variant(
        self, variant_id: uuid.UUID, updates: dict[str, object]
    ) -> PlatformVariant:
        variant = await self.session.get(PlatformVariant, variant_id)
        if variant is None:
            raise NotFoundError("PlatformVariant not found")
        for field in ("title", "caption", "description", "hashtags", "settings"):
            if field in updates and updates[field] is not None:
                setattr(variant, field, updates[field])
        self._validate_lengths(
            variant.platform, variant.title, variant.caption, variant.description
        )
        variant.revision += 1
        variant.content_hash = self.content_hash(
            {
                "title": variant.title,
                "caption": variant.caption,
                "description": variant.description,
                "hashtags": variant.hashtags,
                "settings": variant.settings,
                "video_path": variant.video_path,
                "thumbnail_path": variant.thumbnail_path,
            }
        )
        await self.session.commit()
        await self.session.refresh(variant)
        return variant

    async def list_variants(self, package_id: uuid.UUID) -> Sequence[PlatformVariant]:
        return (
            await self.session.scalars(
                select(PlatformVariant)
                .where(PlatformVariant.publish_package_id == package_id)
                .order_by(PlatformVariant.platform)
            )
        ).all()

    async def _adapt(
        self,
        package: PublishPackage,
        video: VideoProject,
        draft: ContentDraft | None,
        platform: PublishingPlatform,
    ) -> PlatformAdaptationOutput:
        project = await self.session.get(Project, package.project_id)
        source = await self.session.get(SourceItem, video.source_item_id)
        if project is None or source is None:
            raise NotFoundError("Package context not found")
        facts = source.content_analysis.get("source_facts", [])
        system = (
            "You adapt already approved content for one publishing platform. "
            "Return structured output only. Never invent or change facts, numbers, names, URLs "
            "or claims. Hashtags must be separate values without #. Keep the author's language."
        )
        platform_rules = {
            PublishingPlatform.TELEGRAM: (
                "Write a detailed Telegram post with useful technical context. The title may be "
                "part of the post. Avoid clickbait and keep it readable."
            ),
            PublishingPlatform.YOUTUBE: (
                "Write a precise YouTube title and a useful description. Caption should be empty. "
                "The first description lines must explain the technical value."
            ),
            PublishingPlatform.TIKTOK: (
                "Write a short conversational TikTok caption, distinct from YouTube and Telegram. "
                "Keep the title compact and do not add unsupported trends or claims."
            ),
        }[platform]
        prompt = (
            f"TARGET_PLATFORM={platform.value}\n{platform_rules}\n\n"
            f"Project: {project.name}\nAudience: {project.target_audience}\n"
            f"Brand context: {project.brand_context}\nTopic: {source.topic or ''}\n"
            f"Verified source facts: {json.dumps(facts, ensure_ascii=False)}\n"
            f"Approved title: {package.base_title}\nApproved caption: {package.base_caption}\n"
            f"Approved description: {package.base_description}\n"
            f"Approved script: {draft.script if draft else source.transcript or ''}\n"
            f"Approved CTA: {draft.call_to_action if draft else ''}"
        )
        result = await self.ai.generate_structured(
            system_prompt=system, user_prompt=prompt, response_model=PlatformAdaptationOutput
        )
        self._validate_lengths(platform, result.title, result.caption, result.description)
        return result

    def _variant_payload(
        self,
        package: PublishPackage,
        video: VideoProject,
        brand: Project,
        adaptation: PlatformAdaptationOutput,
        platform: PublishingPlatform,
    ) -> dict[str, object]:
        profile = self.profiles.get(platform)
        settings: dict[str, object] = {}
        if platform == PublishingPlatform.YOUTUBE:
            settings = {
                "format": "short",
                "privacy_status": "private",
                "made_for_kids": False,
                "category_id": "28",
            }
        elif platform == PublishingPlatform.TIKTOK:
            requires_rerender = any(
                (
                    brand.brand_preset.get("watermark_enabled"),
                    brand.brand_preset.get("logo_path"),
                    brand.brand_preset.get("outro_path"),
                    video.render_settings.get("branding_enabled"),
                    video.render_settings.get("watermark_enabled"),
                    video.render_settings.get("promotional_overlay"),
                )
            )
            settings = {
                "privacy_level": "SELF_ONLY",
                "disable_comment": False,
                "disable_duet": False,
                "disable_stitch": False,
                "render_overrides": {
                    "branding_enabled": False,
                    "watermark_enabled": False,
                    "hook_overlay": False,
                },
                "duration_seconds": video.metrics.get("output_duration", video.target_duration),
                "user_consent_confirmed": False,
                "requires_rerender": requires_rerender,
            }
        settings["call_to_action"] = adaptation.call_to_action
        payload: dict[str, object] = {
            "video_path": (
                None
                if platform == PublishingPlatform.TIKTOK and settings.get("requires_rerender")
                else package.master_video_path
            ),
            "thumbnail_path": package.master_thumbnail_path,
            "title": adaptation.title,
            "caption": adaptation.caption,
            "description": adaptation.description,
            "hashtags": adaptation.hashtags,
            "settings": settings,
            "media_profile": profile.model_dump(mode="json"),
        }
        payload["content_hash"] = self.content_hash(payload)
        return payload

    def _validate_lengths(
        self, platform: PublishingPlatform, title: str, caption: str, description: str
    ) -> None:
        profile = self.profiles.get(platform)
        if profile.max_title_length and len(title) > profile.max_title_length:
            raise InvalidStateError(f"{platform.value} title is too long")
        if profile.max_caption_length and len(caption) > profile.max_caption_length:
            raise InvalidStateError(f"{platform.value} caption is too long")
        if profile.max_description_length and len(description) > profile.max_description_length:
            raise InvalidStateError(f"{platform.value} description is too long")

    @staticmethod
    def content_hash(payload: object) -> str:
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str).encode()
        return hashlib.sha256(encoded).hexdigest()
