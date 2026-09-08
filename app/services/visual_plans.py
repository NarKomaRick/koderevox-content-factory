import re
import uuid
from collections.abc import Sequence

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider
from app.core.config import Settings
from app.models import AssetUsage, SourceItem, VideoProject, VisualAsset
from app.models.enums import AssetStatus, AssetType, VisualLayout
from app.schemas.video import EditPlan
from app.schemas.visual import AssetRecommendationBatch, VisualInsertion, VisualPlan
from app.services.errors import InvalidStateError, NotFoundError


class VisualPlanValidator:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def validate(
        self,
        plan: VisualPlan,
        *,
        video_project: VideoProject,
        duration: float,
        allow_missing_optional: bool = False,
    ) -> VisualPlan:
        ordered = sorted(plan.insertions, key=lambda item: (item.start, item.end))
        maximum = max(1, int(duration / 60 * self.settings.visual_max_inserts_per_minute) + 1)
        if len(ordered) > maximum:
            raise InvalidStateError("VisualPlan exceeds VISUAL_MAX_INSERTS_PER_MINUTE")
        for index, item in enumerate(ordered):
            insertion_duration = item.end - item.start
            if item.end > duration + 0.01:
                raise InvalidStateError("Visual insertion exceeds final video duration")
            if insertion_duration < self.settings.visual_min_insert_duration:
                raise InvalidStateError("Visual insertion is shorter than configured minimum")
            if insertion_duration > self.settings.visual_max_insert_duration:
                raise InvalidStateError("Visual insertion is longer than configured maximum")
            asset = await self.session.get(VisualAsset, item.asset_id)
            if asset is None or asset.project_id != video_project.project_id:
                if allow_missing_optional and not item.required:
                    continue
                raise InvalidStateError("Visual asset does not exist in this project")
            if asset.status != AssetStatus.READY:
                if allow_missing_optional and not item.required:
                    continue
                raise InvalidStateError("Visual asset is not READY")
            self._compatible(item, asset)
            if index:
                previous = ordered[index - 1]
                if item.start < previous.end:
                    raise InvalidStateError("Overlapping visual insertions are not supported")
                if item.start - previous.end < self.settings.visual_min_gap_seconds:
                    raise InvalidStateError("Visual insertions violate VISUAL_MIN_GAP_SECONDS")
        return plan.model_copy(update={"insertions": ordered})

    @staticmethod
    def _compatible(insertion: VisualInsertion, asset: VisualAsset) -> None:
        if insertion.layout == VisualLayout.DEVICE_FRAME and asset.type not in {
            AssetType.SCREENSHOT,
            AssetType.IMAGE,
        }:
            raise InvalidStateError("DEVICE_FRAME requires an image or screenshot")
        if insertion.layout == VisualLayout.CODE_CARD and asset.type != AssetType.CODE:
            raise InvalidStateError("CODE_CARD requires a CODE asset")


class VisualPlanService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        ai_provider: AIProvider | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.ai = ai_provider
        self.validator = VisualPlanValidator(session, settings)

    async def get(self, video_project_id: uuid.UUID) -> VisualPlan:
        project = await self._project(video_project_id)
        return VisualPlan.model_validate(project.visual_plan or {})

    async def replace(self, video_project_id: uuid.UUID, plan: VisualPlan) -> VideoProject:
        project = await self._project(video_project_id)
        validated = await self.validator.validate(
            plan, video_project=project, duration=self._duration(project)
        )
        project.visual_plan = validated.model_dump(mode="json")
        project.render_fingerprint = None
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def add(self, video_project_id: uuid.UUID, insertion: VisualInsertion) -> VideoProject:
        current = await self.get(video_project_id)
        return await self.replace(
            video_project_id,
            current.model_copy(update={"insertions": [*current.insertions, insertion]}),
        )

    async def remove(self, video_project_id: uuid.UUID, index: int) -> VideoProject:
        current = await self.get(video_project_id)
        if index < 0 or index >= len(current.insertions):
            raise NotFoundError("Visual insertion not found")
        return await self.replace(
            video_project_id,
            current.model_copy(
                update={
                    "insertions": [
                        item
                        for item_index, item in enumerate(current.insertions)
                        if item_index != index
                    ]
                }
            ),
        )

    async def suggest(
        self, video_project_id: uuid.UUID, instruction: str | None = None
    ) -> VisualPlan:
        project = await self._project(video_project_id)
        source = await self.session.get(SourceItem, project.source_item_id)
        if source is None:
            raise NotFoundError("SourceItem not found")
        transcript = " ".join(filter(None, [source.transcript, source.summary, instruction]))
        terms = self._search_terms(transcript)
        candidates = await self._retrieve(project.project_id, terms)
        duration = self._duration(project)
        if self.ai is not None and candidates:
            ai_plan = await self._ai_suggest(
                source=source,
                candidates=candidates,
                duration=duration,
                instruction=instruction,
            )
            if ai_plan is not None:
                return await self.validator.validate(
                    ai_plan, video_project=project, duration=duration
                )
        insertions: list[VisualInsertion] = []
        cursor = min(5.0, max(0.0, duration * 0.15))
        for asset in candidates[:3]:
            length = min(4.0, self.settings.visual_max_insert_duration)
            if cursor + length > duration:
                break
            layout = self._layout(asset)
            insertions.append(
                VisualInsertion(
                    start=round(cursor, 2),
                    end=round(cursor + length, 2),
                    asset_id=asset.id,
                    role="code_example" if asset.type == AssetType.CODE else "illustration",
                    layout=layout,
                    reason=f"Материал совпадает с темой: {asset.title}",
                    required=False,
                )
            )
            cursor += length + self.settings.visual_min_gap_seconds + 3
        plan = VisualPlan(
            insertions=insertions,
            reasoning_summary="Conservative metadata retrieval; user confirmation required.",
        )
        return await self.validator.validate(plan, video_project=project, duration=duration)

    async def _ai_suggest(
        self,
        *,
        source: SourceItem,
        candidates: Sequence[VisualAsset],
        duration: float,
        instruction: str | None,
    ) -> VisualPlan | None:
        assert self.ai is not None
        candidate_payload = [
            {
                "id": str(asset.id),
                "type": asset.type.value,
                "title": asset.title,
                "description": asset.description,
                "tags": asset.tags,
                "extracted_text": (asset.extracted_text or "")[:1500],
                "analysis": asset.analysis,
            }
            for asset in candidates[:20]
        ]
        prompt = (
            "Create a conservative VisualPlan recommendation for a technical video. "
            "Choose only from candidate IDs. Use an insertion only when it clarifies speech, "
            "shows the real product, explains code/concepts, or hides a jump cut. No memes, "
            "stock or decorative noise. Respect 1.5-8 second durations and 2 second gaps. "
            f"Final duration: {duration}. Instruction: {instruction or 'none'}. "
            f"Transcript segments: {source.transcript_segments}. "
            f"Content intelligence: {source.content_analysis}. Candidates: {candidate_payload}"
        )
        try:
            result = await self.ai.generate_structured(
                system_prompt=(
                    "You select restrained, useful B-roll. You never emit FFmpeg or invent assets."
                ),
                user_prompt=prompt,
                response_model=AssetRecommendationBatch,
            )
            candidate_ids = {asset.id for asset in candidates}
            if any(item.asset_id not in candidate_ids for item in result.recommendations):
                return None
            return VisualPlan(
                insertions=[
                    VisualInsertion(
                        start=item.start,
                        end=item.end,
                        asset_id=item.asset_id,
                        role=item.role,
                        layout=item.layout,
                        reason=item.reason,
                    )
                    for item in result.recommendations
                ],
                reasoning_summary=result.reasoning_summary,
            )
        except Exception:
            return None

    async def apply_instruction(
        self, video_project_id: uuid.UUID, instruction: str
    ) -> VideoProject:
        current = await self.get(video_project_id)
        lowered = instruction.casefold()
        items = list(current.insertions)
        if "убери второй" in lowered and len(items) >= 2:
            items.pop(1)
        elif "не показывай код" in lowered:
            code_ids = set(
                await self.session.scalars(
                    select(VisualAsset.id).where(VisualAsset.type == AssetType.CODE)
                )
            )
            items = [item for item in items if item.asset_id not in code_ids]
        elif "на весь экран" in lowered and items:
            items[-1] = items[-1].model_copy(update={"layout": VisualLayout.FULLSCREEN})
        else:
            raise InvalidStateError("Instruction needs an explicit supported visual operation")
        plan = VisualPlan(insertions=items, reasoning_summary=instruction)
        return await self.replace(video_project_id, plan)

    async def record_usage(self, video_project_id: uuid.UUID, plan: VisualPlan) -> None:
        existing: Sequence[AssetUsage] = (
            await self.session.scalars(
                select(AssetUsage).where(AssetUsage.video_project_id == video_project_id)
            )
        ).all()
        keys = {(str(item.asset_id), item.start, item.end, item.usage_type) for item in existing}
        desired = {
            (str(item.asset_id), item.start, item.end, item.role): item for item in plan.insertions
        }
        for usage in existing:
            key = (str(usage.asset_id), usage.start, usage.end, usage.usage_type)
            if key not in desired:
                await self.session.delete(usage)
        for key, item in desired.items():
            if key not in keys:
                self.session.add(
                    AssetUsage(
                        asset_id=item.asset_id,
                        video_project_id=video_project_id,
                        start=item.start,
                        end=item.end,
                        usage_type=item.role,
                    )
                )
        await self.session.flush()

    async def _retrieve(self, project_id: uuid.UUID, terms: list[str]) -> Sequence[VisualAsset]:
        usage_count = (
            select(func.count(AssetUsage.id))
            .where(AssetUsage.asset_id == VisualAsset.id)
            .correlate(VisualAsset)
            .scalar_subquery()
        )
        statement = select(VisualAsset).where(
            VisualAsset.project_id == project_id,
            VisualAsset.status == AssetStatus.READY,
        )
        if terms:
            expressions = []
            for term in terms[:12]:
                pattern = f"%{term}%"
                expressions.extend(
                    [
                        VisualAsset.title.ilike(pattern),
                        VisualAsset.description.ilike(pattern),
                        VisualAsset.extracted_text.ilike(pattern),
                        cast(VisualAsset.tags, String).ilike(pattern),
                    ]
                )
            statement = statement.where(or_(*expressions))
        return (
            await self.session.scalars(
                statement.order_by(
                    VisualAsset.favorite.desc(), usage_count.asc(), VisualAsset.created_at.desc()
                ).limit(20)
            )
        ).all()

    async def _project(self, video_project_id: uuid.UUID) -> VideoProject:
        project = await self.session.get(VideoProject, video_project_id)
        if project is None:
            raise NotFoundError("VideoProject not found")
        return project

    @staticmethod
    def _duration(project: VideoProject) -> float:
        if project.metrics.get("output_duration"):
            return float(project.metrics["output_duration"])
        plan = EditPlan.model_validate(project.edit_plan)
        return sum(clip.source_end - clip.source_start for clip in plan.clips)

    @staticmethod
    def _search_terms(text: str) -> list[str]:
        tokens = re.findall(r"[\wА-Яа-яЁё+#.]{3,}", text.casefold())
        stop = {"который", "когда", "потом", "этого", "просто", "сделали", "покажи"}
        return list(dict.fromkeys(token for token in tokens if token not in stop))[:20]

    @staticmethod
    def _layout(asset: VisualAsset) -> VisualLayout:
        if asset.type == AssetType.CODE:
            return VisualLayout.CODE_CARD
        if asset.type == AssetType.SCREENSHOT and (asset.height or 0) > (asset.width or 0):
            return VisualLayout.DEVICE_FRAME
        if asset.type in {AssetType.VIDEO, AssetType.SCREEN_RECORDING}:
            return VisualLayout.FULLSCREEN
        return VisualLayout.PICTURE_IN_PICTURE
