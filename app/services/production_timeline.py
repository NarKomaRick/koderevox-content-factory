import re
import uuid
from difflib import SequenceMatcher

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import (
    ProductionMaterial,
    ProductionProject,
    TimelineRevision,
    VisualAsset,
    VoiceoverTrack,
)
from app.models.enums import AssetType, ProductionStatus, TimelineTrack
from app.schemas.production import (
    GapWarning,
    PlacementCandidate,
    PlacementResult,
    ProductionTimeline,
    RenderProfile,
    TimelineItem,
)
from app.services.errors import InvalidStateError, NotFoundError
from app.services.production_projects import AssetCandidateRetriever


class SemanticPlacementService:
    def find(self, instruction: str, voiceover: VoiceoverTrack) -> PlacementResult:
        phrase = self._phrase(instruction)
        ranges = list(voiceover.alignment.get("sections", [])) or voiceover.segments
        ranked: list[PlacementCandidate] = []
        phrase_tokens = self._normalize(phrase)
        for item in ranges:
            text = str(item.get("voice_text") or item.get("text") or "")
            script_text = str(item.get("script_text") or "")
            searchable = self._normalize(f"{text} {script_text}")
            score = max(
                SequenceMatcher(None, phrase_tokens, self._normalize(text)).ratio(),
                SequenceMatcher(None, phrase_tokens, self._normalize(script_text)).ratio(),
            )
            if phrase_tokens and phrase_tokens in searchable:
                score = max(score, 0.96)
            start, end = float(item.get("start", 0)), float(item.get("end", 0))
            if "после" in instruction.casefold():
                start = min(voiceover.duration - 0.1, end)
                end = min(voiceover.duration, start + 2.5)
            if end > start:
                ranked.append(
                    PlacementCandidate(
                        start=start,
                        end=end,
                        text=text,
                        confidence=round(score, 4),
                    )
                )
        ranked.sort(key=lambda item: item.confidence, reverse=True)
        candidates = [item for item in ranked[:3] if item.confidence >= 0.28]
        if not candidates or candidates[0].confidence < 0.42:
            return PlacementResult(status="no_match", candidates=candidates)
        ambiguous = (
            len(candidates) > 1
            and candidates[1].confidence >= 0.55
            and candidates[0].confidence - candidates[1].confidence < 0.12
        )
        return PlacementResult(status="ambiguous" if ambiguous else "unique", candidates=candidates)

    @staticmethod
    def _phrase(instruction: str) -> str:
        lowered = instruction.casefold()
        markers = (
            "когда говорю про ",
            "где говорю про ",
            "когда говорю, что ",
            "где говорю, что ",
            "в моменте про ",
            "про ",
            "после фразы ",
        )
        for marker in markers:
            if marker in lowered:
                return instruction[lowered.index(marker) + len(marker) :].strip(' .!?"«»')
        return instruction

    @staticmethod
    def _normalize(text: str) -> str:
        return " ".join(re.findall(r"[\w+#.]+", text.casefold(), flags=re.UNICODE))


class TimelineRevisionService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(
        self,
        production_project_id: uuid.UUID,
        timeline: ProductionTimeline,
        *,
        user_instruction: str | None = None,
        change_summary: str | None = None,
    ) -> TimelineRevision:
        production = await self.session.get(ProductionProject, production_project_id)
        if production is None:
            raise NotFoundError("ProductionProject not found")
        number = (
            int(
                await self.session.scalar(
                    select(func.max(TimelineRevision.revision_number)).where(
                        TimelineRevision.production_project_id == production_project_id
                    )
                )
                or 0
            )
            + 1
        )
        revision = TimelineRevision(
            production_project_id=production_project_id,
            revision_number=number,
            timeline_json=timeline.model_dump(mode="json"),
            user_instruction=user_instruction,
            change_summary=change_summary,
        )
        self.session.add(revision)
        await self.session.flush()
        production.active_timeline_revision_id = revision.id
        production.status = ProductionStatus.ROUGH_CUT
        await self.session.commit()
        await self.session.refresh(revision)
        return revision

    async def active(self, production_project_id: uuid.UUID) -> TimelineRevision:
        production = await self.session.get(ProductionProject, production_project_id)
        if production is None or not production.active_timeline_revision_id:
            raise NotFoundError("Active timeline revision not found")
        revision = await self.session.get(TimelineRevision, production.active_timeline_revision_id)
        if revision is None:
            raise NotFoundError("Active timeline revision not found")
        return revision

    async def history(self, production_project_id: uuid.UUID) -> list[TimelineRevision]:
        return list(
            (
                await self.session.scalars(
                    select(TimelineRevision)
                    .where(TimelineRevision.production_project_id == production_project_id)
                    .order_by(TimelineRevision.revision_number)
                )
            ).all()
        )

    async def rollback(
        self, production_project_id: uuid.UUID, revision_id: uuid.UUID
    ) -> TimelineRevision:
        production = await self.session.get(ProductionProject, production_project_id)
        revision = await self.session.get(TimelineRevision, revision_id)
        if (
            production is None
            or revision is None
            or revision.production_project_id != production.id
        ):
            raise NotFoundError("Timeline revision not found")
        source = ProductionTimeline.model_validate(revision.timeline_json)
        return await self.create(
            production_project_id,
            source,
            user_instruction=f"rollback:{revision.revision_number}",
            change_summary=f"Возврат к revision {revision.revision_number}",
        )


class AutoAssemblyService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.retriever = AssetCandidateRetriever(session)
        self.revisions = TimelineRevisionService(session)

    async def assemble(self, production_project_id: uuid.UUID) -> TimelineRevision:
        production, voiceover = await self._dependencies(production_project_id)
        blocks = list(voiceover.alignment.get("sections", [])) or voiceover.segments
        items = [
            TimelineItem(
                track=TimelineTrack.AUDIO_MASTER,
                start=0,
                end=voiceover.duration,
                metadata={"voiceover_track_id": str(voiceover.id)},
            ),
            TimelineItem(
                track=TimelineTrack.SUBTITLES,
                start=0,
                end=voiceover.duration,
                metadata={"source": "voiceover.words"},
            ),
        ]
        used_assets: set[uuid.UUID] = set()
        for block in blocks:
            start = max(0.0, float(block.get("start", 0)))
            end = min(voiceover.duration, float(block.get("end", voiceover.duration)))
            if end - start < 0.2:
                continue
            text = str(block.get("voice_text") or block.get("text") or "")
            candidates = await self.retriever.retrieve(production.id, text, limit=5)
            selected = next(
                (row for row in candidates if row[1].id not in used_assets and row[2] > 0.1), None
            )
            if selected:
                material, asset, score = selected
                used_assets.add(asset.id)
                material.is_used = True
                items.append(self._visual_item(asset, start, end, score))
            elif end - start >= self.settings.assembly_target_visual_change_max_seconds:
                items.append(
                    TimelineItem(
                        track=TimelineTrack.TEXT,
                        start=start,
                        end=min(
                            end, start + self.settings.assembly_target_visual_change_max_seconds
                        ),
                        text=self._card_text(text),
                        layout="code_card",
                        metadata={"generated_fallback": True},
                    )
                )
        timeline = ProductionTimeline(
            duration=voiceover.duration,
            voiceover_track_id=voiceover.id,
            items=sorted(items, key=lambda item: (item.start, item.track.value)),
        )
        production.status = ProductionStatus.ASSEMBLING
        await self.session.flush()
        return await self.revisions.create(
            production.id, timeline, change_summary="Первый автоматический voiceover-driven монтаж"
        )

    async def insert_locked(
        self,
        production_project_id: uuid.UUID,
        material_id: uuid.UUID,
        instruction: str,
        *,
        candidate_index: int | None = None,
    ) -> tuple[PlacementResult, TimelineRevision | None]:
        active = await self.revisions.active(production_project_id)
        timeline = ProductionTimeline.model_validate(active.timeline_json)
        voiceover = await self.session.get(VoiceoverTrack, timeline.voiceover_track_id)
        material = await self.session.get(ProductionMaterial, material_id)
        if (
            voiceover is None
            or material is None
            or material.production_project_id != production_project_id
        ):
            raise NotFoundError("Voiceover or production material not found")
        result = SemanticPlacementService().find(instruction, voiceover)
        if result.status == "no_match" or not result.candidates:
            return result, None
        if result.status == "ambiguous" and candidate_index is None:
            return result, None
        choice = result.candidates[candidate_index or 0]
        if material.asset_id is None:
            raise InvalidStateError("Only a VisualAsset can be placed on a visual track")
        asset = await self.session.get(VisualAsset, material.asset_id)
        if asset is None:
            raise NotFoundError("VisualAsset not found")
        duration_hint = (
            1.0 if "секунд" in instruction.casefold() and "одн" in instruction.casefold() else None
        )
        end = min(timeline.duration, choice.start + duration_hint) if duration_hint else choice.end
        item = self._visual_item(
            asset, choice.start, max(choice.start + 0.1, end), choice.confidence
        )
        item.locked_by_user = True
        item.metadata = {**item.metadata, "instruction": instruction, "semantic_match": choice.text}
        timeline.items.append(item)
        material.is_used = True
        material.is_user_locked = True
        material.user_instruction = instruction
        revision = await self.revisions.create(
            production_project_id,
            timeline,
            user_instruction=instruction,
            change_summary=f"Добавлена закреплённая вставка {asset.filename}",
        )
        return result, revision

    async def local_replan(
        self, production_project_id: uuid.UUID, instruction: str
    ) -> TimelineRevision:
        active = await self.revisions.active(production_project_id)
        timeline = ProductionTimeline.model_validate(active.timeline_json)
        lowered = instruction.casefold()
        scope_start, scope_end = 0.0, timeline.duration
        seconds = re.search(r"(?:первые|перв(?:ые|ую))\s+(\d+(?:[.,]\d+)?)", lowered)
        if seconds:
            scope_end = min(timeline.duration, float(seconds.group(1).replace(",", ".")))
        midpoint = timeline.duration / 2
        if "после середины" in lowered:
            scope_start = midpoint
        changed: list[TimelineItem] = []
        for item in timeline.items:
            if item.locked_by_user or item.end <= scope_start or item.start >= scope_end:
                changed.append(item)
                continue
            is_meme = item.metadata.get("role") == "meme"
            if ("убери все мем" in lowered or "мемов меньше" in lowered) and is_meme:
                continue
            if "быстр" in lowered or "динамич" in lowered:
                maximum = self.settings.assembly_target_visual_change_max_seconds
                item.end = max(item.start + 0.3, min(item.end, item.start + maximum))
            if (
                "скриншотов слишком много" in lowered
                and item.metadata.get("asset_type") == "screenshot"
            ):
                if int(item.start) % 2:
                    continue
            changed.append(item)
        timeline.items = changed
        return await self.revisions.create(
            production_project_id,
            timeline,
            user_instruction=instruction,
            change_summary=(
                f"Локальная правка {scope_start:.1f}–{scope_end:.1f} sec; locked items preserved"
            ),
        )

    async def _dependencies(
        self, production_project_id: uuid.UUID
    ) -> tuple[ProductionProject, VoiceoverTrack]:
        production = await self.session.get(ProductionProject, production_project_id)
        if production is None or not production.primary_voiceover_id:
            raise InvalidStateError("A ready voiceover is required for assembly")
        voiceover = await self.session.get(VoiceoverTrack, production.primary_voiceover_id)
        if voiceover is None:
            raise NotFoundError("VoiceoverTrack not found")
        return production, voiceover

    @staticmethod
    def _visual_item(asset: VisualAsset, start: float, end: float, score: float) -> TimelineItem:
        is_overlay = (
            "meme" in asset.tags or "мем" in f"{asset.title} {asset.description}".casefold()
        )
        layout = (
            "picture_in_picture"
            if is_overlay
            else ("code_card" if asset.type == AssetType.CODE else "fullscreen")
        )
        return TimelineItem(
            track=TimelineTrack.OVERLAY if is_overlay else TimelineTrack.BROLL,
            start=start,
            end=end,
            asset_id=asset.id,
            layout=layout,
            source_start=0 if asset.duration else None,
            source_end=min(float(asset.duration), end - start) if asset.duration else None,
            metadata={
                "asset_type": asset.type.value,
                "role": "meme" if is_overlay else "visual",
                "retrieval_score": round(score, 4),
                "muted": True,
            },
        )

    @staticmethod
    def _card_text(text: str) -> str:
        words = text.split()
        return " ".join(words[:6]).strip(".,") or "TECH"


class VisualGapAnalyzer:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def analyze(self, timeline: ProductionTimeline) -> list[GapWarning]:
        visual = sorted(
            [
                item
                for item in timeline.items
                if item.track
                in {
                    TimelineTrack.VIDEO_BASE,
                    TimelineTrack.BROLL,
                    TimelineTrack.OVERLAY,
                    TimelineTrack.TEXT,
                }
            ],
            key=lambda item: item.start,
        )
        warnings: list[GapWarning] = []
        cursor = 0.0
        for item in visual:
            if item.start - cursor > self.settings.assembly_target_visual_change_max_seconds:
                warnings.append(
                    self._warning(cursor, item.start, "long gap without a visual change")
                )
            if (
                item.metadata.get("asset_type") == AssetType.SCREENSHOT.value
                and item.end - item.start > self.settings.assembly_max_screenshot_seconds
            ):
                warnings.append(self._warning(item.start, item.end, "screenshot is held too long"))
            cursor = max(cursor, item.end)
        if timeline.duration - cursor > self.settings.assembly_target_visual_change_max_seconds:
            warnings.append(
                self._warning(cursor, timeline.duration, "long gap without a visual change")
            )
        return warnings

    @staticmethod
    def _warning(start: float, end: float, reason: str) -> GapWarning:
        return GapWarning(
            start=start,
            end=end,
            duration=end - start,
            reason=reason,
            recommendations=["existing asset", "text card", "different crop", "leave as is"],
        )


def render_profile(settings: Settings, name: str) -> RenderProfile:
    if name.casefold() == "preview":
        return RenderProfile(
            name="preview",
            width=settings.preview_width,
            height=settings.preview_height,
            crf=settings.preview_crf,
            preset=settings.preview_preset,
            audio_bitrate="96k",
        )
    return RenderProfile(
        name="final",
        width=settings.video_width,
        height=settings.video_height,
        crf=settings.video_crf,
        preset=settings.video_preset,
        audio_bitrate="160k",
    )
