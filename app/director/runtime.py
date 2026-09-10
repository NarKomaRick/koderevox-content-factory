"""Execution boundary between model-generated intent and application-owned editing."""

import uuid
from typing import Any

import structlog
from pydantic import BaseModel, TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.clip_finder import ClipFinder
from app.core.config import Settings
from app.director.context import DirectorContextBuilder
from app.director.policies import DirectorLimits, DirectorToolError
from app.director.schemas import (
    AddGraphicOperation,
    AddTextOperation,
    AddVisualOperation,
    AdjustAudioOperation,
    BlurRegionOperation,
    DirectorToolResult,
    OutputProfile,
    RemoveItemOperation,
    RevisionDiff,
    SetLayoutOperation,
    TimelineOperation,
    VariantRequest,
)
from app.director.tools import DirectorToolRegistry, EmptyArguments, ToolDefinition
from app.editing.layout import LayoutEngine
from app.editing.validation import TimelineValidator
from app.models import (
    DirectorRun,
    DirectorVariant,
    ProductionProject,
    TimelineRevision,
    VideoProject,
    VisualAsset,
    VoiceoverTrack,
)
from app.models.enums import AssetStatus, TimelineTrack, VoiceoverStatus
from app.schemas.production import ProductionTimeline, TimelineItem
from app.services.errors import InvalidStateError, NotFoundError
from app.services.production_rendering import ProductionRenderService
from app.services.production_timeline import TimelineRevisionService
from app.storage.local import LocalStorage

logger = structlog.get_logger()
_OPERATION_ADAPTER: TypeAdapter[TimelineOperation] = TypeAdapter(TimelineOperation)


class DirectorRuntime:
    """A project-scoped runtime. It never accepts shell fragments or filesystem paths."""

    def __init__(
        self,
        session: AsyncSession,
        production_project_id: uuid.UUID,
        settings: Settings | None = None,
    ) -> None:
        self.session = session
        self.production_project_id = production_project_id
        self.settings = settings or Settings()
        self.limits = DirectorLimits.from_settings(self.settings)
        self.context_builder = DirectorContextBuilder(session, self.settings)
        self.revisions = TimelineRevisionService(session)
        self.layout = LayoutEngine(font_path=self.settings.video_font_path)
        self.validator = TimelineValidator(self.layout)
        self.registry = self._build_registry()

    def _build_registry(self) -> DirectorToolRegistry:
        definitions = [
            ToolDefinition(
                "inspect_project", "Inspect bounded production context.", EmptyArguments
            ),
            ToolDefinition(
                "inspect_voiceover", "Inspect bounded voiceover timing.", EmptyArguments
            ),
            ToolDefinition(
                "inspect_timeline",
                "Inspect the active immutable timeline revision.",
                EmptyArguments,
            ),
            ToolDefinition(
                "list_assets", "List ready assets inside this project only.", EmptyArguments
            ),
            ToolDefinition("inspect_asset", "Inspect one project asset by ID.", AssetIdArguments),
            ToolDefinition(
                "find_visuals", "Find relevant cached assets and scene clips.", FindVisualsArguments
            ),
            ToolDefinition(
                "find_visual_candidates",
                "Return several explainable visual candidates; the Director chooses one.",
                FindVisualsArguments,
            ),
            ToolDefinition(
                "find_clip", "Select a concrete range from a long video asset.", FindClipArguments
            ),
            ToolDefinition(
                "add_visual", "Add a validated visual clip to the timeline.", AddVisualOperation
            ),
            ToolDefinition(
                "add_image", "Add a validated image asset to the timeline.", AddVisualOperation
            ),
            ToolDefinition(
                "add_text", "Add text using deterministic layout placement.", AddTextOperation
            ),
            ToolDefinition(
                "add_graphic", "Add a safe graphics DSL primitive.", AddGraphicOperation
            ),
            ToolDefinition(
                "blur_region", "Add a bounded blur operation marker.", BlurRegionOperation
            ),
            ToolDefinition(
                "set_layout", "Change the layout of an unlocked timeline item.", SetLayoutOperation
            ),
            ToolDefinition(
                "add_transition", "Add a supported deterministic transition.", TransitionArguments
            ),
            ToolDefinition(
                "adjust_audio",
                "Adjust audio metadata without changing voiceover duration.",
                AdjustAudioOperation,
            ),
            ToolDefinition("remove_item", "Remove an unlocked timeline item.", RemoveItemOperation),
            ToolDefinition(
                "render_preview",
                "Render a fast preview using application-owned paths.",
                PreviewArguments,
            ),
            ToolDefinition(
                "inspect_render", "Inspect the current render metadata.", EmptyArguments
            ),
            ToolDefinition(
                "validate_timeline", "Run deterministic hard validation.", EmptyArguments
            ),
            ToolDefinition(
                "undo", "Rollback to a previous revision without destructive edits.", UndoArguments
            ),
            ToolDefinition(
                "create_variant",
                "Create non-active local branches for a bounded range.",
                VariantRequest,
            ),
            ToolDefinition(
                "compare_revisions",
                "Compare two immutable timeline revisions.",
                CompareRevisionsArguments,
            ),
            ToolDefinition("finalize", "Validate and render the final output.", EmptyArguments),
        ]
        return DirectorToolRegistry(definitions)

    async def context(self, *, profile_name: str | None = None) -> dict[str, Any]:
        return await self.context_builder.build(
            self.production_project_id, profile_name=profile_name
        )

    async def execute(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        run: DirectorRun | None = None,
        step: int = 0,
    ) -> DirectorToolResult:
        try:
            parsed = self.registry.parse(tool_name, arguments)
            result = await self._dispatch(tool_name, parsed)
            await logger.ainfo("director_tool_result", tool=tool_name, ok=result.ok, step=step)
            return result
        except (DirectorToolError, InvalidStateError, NotFoundError, ValueError) as exc:
            if isinstance(exc, DirectorToolError):
                error = exc.as_dict()
            else:
                error = {"code": "TOOL_EXECUTION_ERROR", "message": str(exc), "recoverable": True}
            await logger.awarning(
                "director_tool_result", tool=tool_name, ok=False, error_code=error["code"]
            )
            return DirectorToolResult(ok=False, error=error)

    async def _dispatch(self, name: str, parsed: Any) -> DirectorToolResult:
        if name == "inspect_project":
            return DirectorToolResult(ok=True, data=await self.context())
        if name == "inspect_voiceover":
            context = await self.context()
            return DirectorToolResult(ok=True, data={"voiceover": context["voiceover"]})
        if name == "inspect_timeline":
            context = await self.context()
            return DirectorToolResult(ok=True, data={"timeline": context["timeline"]})
        if name == "list_assets":
            context = await self.context()
            return DirectorToolResult(ok=True, data={"assets": context["assets"]})
        if name == "inspect_asset":
            asset = await self._asset(parsed.asset_id)
            return DirectorToolResult(
                ok=True, data={"asset": self.context_builder._asset_manifest(asset)}
            )
        if name in {"find_visuals", "find_visual_candidates", "find_clip"}:
            return await self._find(name, parsed)
        if name in {
            "add_visual",
            "add_image",
            "add_text",
            "add_graphic",
            "blur_region",
            "adjust_audio",
            "remove_item",
        }:
            operation = (
                _OPERATION_ADAPTER.validate_python(
                    {"operation": name, **parsed.model_dump(mode="json")}
                )
                if name != "add_image"
                else _OPERATION_ADAPTER.validate_python(
                    {"operation": "add_visual", **parsed.model_dump(mode="json")}
                )
            )
            return await self._apply_operation(operation)
        if name == "set_layout":
            return await self._set_layout(parsed)
        if name == "add_transition":
            return await self._set_transition(parsed)
        if name == "render_preview":
            return await self._render(profile_name="preview", start=parsed.start, end=parsed.end)
        if name == "inspect_render":
            return await self._inspect_render()
        if name == "validate_timeline":
            return await self._validate()
        if name == "undo":
            return await self._undo(parsed.revision_id)
        if name == "create_variant":
            return await self._create_variant(parsed)
        if name == "compare_revisions":
            return await self._compare_revisions(parsed)
        if name == "finalize":
            validation = await self._validate()
            if not validation.ok:
                return validation
            return await self._render(profile_name="final", start=None, end=None)
        raise DirectorToolError("UNKNOWN_TOOL", f"Unknown Director tool: {name}")

    async def _apply_operation(self, operation: TimelineOperation) -> DirectorToolResult:
        asset = (
            await self._asset(operation.asset_id)
            if isinstance(operation, AddVisualOperation)
            else None
        )
        timeline = await self._timeline()
        end = getattr(operation, "end", None)
        if end is not None and end > timeline.duration + 0.05:
            raise DirectorToolError("INVALID_TIMELINE_RANGE", "end exceeds voiceover duration")
        if isinstance(operation, AddVisualOperation):
            assert asset is not None
            if asset.status != AssetStatus.READY:
                raise DirectorToolError("ASSET_NOT_READY", "Asset is not ready")
            source_start = operation.source_start
            source_end = operation.source_end
            if asset.duration is not None:
                source_start = 0 if source_start is None else source_start
                source_end = operation.end - operation.start if source_end is None else source_end
                if source_start >= asset.duration or source_end > asset.duration + 0.05:
                    raise DirectorToolError(
                        "INVALID_SOURCE_RANGE", "Clip range exceeds asset duration"
                    )
            track = TimelineTrack(operation.track)
            timeline.items.append(
                TimelineItem(
                    track=track,
                    start=operation.start,
                    end=operation.end,
                    asset_id=asset.id,
                    layout=operation.layout,
                    source_start=source_start,
                    source_end=source_end,
                    locked_by_user=operation.locked_by_user,
                    metadata={
                        "asset_type": asset.type.value,
                        "director": True,
                        "muted": True,
                        "visual_intent": operation.visual_intent
                        or {
                            "purpose": "interest",
                            "reason": (
                                "Application-supplied visual selected for the requested range."
                            ),
                            "importance": 0.5,
                        },
                    },
                )
            )
        elif isinstance(operation, AddTextOperation):
            profile = await self._profile()
            occupied = self._text_boxes(timeline)
            box = self.layout.place(
                operation.text,
                profile,
                anchor=operation.anchor,
                font_size=operation.font_size,
                occupied=occupied,
            )
            timeline.items.append(
                TimelineItem(
                    track=TimelineTrack.TEXT,
                    start=operation.start,
                    end=operation.end,
                    text=box.text,
                    locked_by_user=operation.locked_by_user,
                    metadata={
                        "director": True,
                        "anchor": box.anchor,
                        "style": operation.style,
                        "font_size": box.font_size,
                        "text_layout": {
                            "x": box.x,
                            "y": box.y,
                            "width": box.width,
                            "height": box.height,
                            "font_size": box.font_size,
                            "anchor": box.anchor,
                        },
                        "semantic_role": operation.semantic_role,
                        "reason": operation.reason or "Text clarifies the current story beat.",
                    },
                )
            )
        elif isinstance(operation, AddGraphicOperation):
            timeline.items.append(
                TimelineItem(
                    track=TimelineTrack.GRAPHICS,
                    start=operation.start,
                    end=operation.end,
                    layout="graphic",
                    metadata={
                        "director": True,
                        "graphic": operation.kind,
                        "content": operation.content,
                        "style": operation.style,
                        "reason": operation.reason
                        or "Graphic explains or emphasizes the current beat.",
                    },
                )
            )
        elif isinstance(operation, BlurRegionOperation):
            if operation.mode == "background_blur":
                target = next(
                    (
                        item
                        for item in timeline.items
                        if item.asset_id
                        and item.start <= operation.start
                        and item.end >= operation.end
                    ),
                    None,
                )
                if target is None:
                    raise DirectorToolError(
                        "NO_VISUAL_TO_BLUR", "No visual covers the requested blur range"
                    )
                if target.locked_by_user:
                    raise DirectorToolError(
                        "USER_LOCKED_ITEM", "Director cannot change a user-locked item"
                    )
                target.layout = "blur_background_fit"
                target.metadata["blur"] = operation.model_dump(mode="json")
            else:
                timeline.items.append(
                    TimelineItem(
                        track=TimelineTrack.OVERLAY,
                        start=operation.start,
                        end=operation.end,
                        layout="blur_region",
                        metadata={"director": True, "blur": operation.model_dump(mode="json")},
                    )
                )
        elif isinstance(operation, AdjustAudioOperation):
            for item in timeline.items:
                if item.track == TimelineTrack.AUDIO_MASTER:
                    adjustments = list(item.metadata.get("director_audio_adjustments", []))
                    adjustments.append(operation.model_dump(mode="json"))
                    item.metadata["director_audio_adjustments"] = adjustments
                    break
        elif isinstance(operation, RemoveItemOperation):
            timeline.items = [
                item
                for item in timeline.items
                if self._remove_if_allowed(item, operation.timeline_item_id)
            ]
        revision = await self.revisions.create(
            self.production_project_id,
            timeline,
            change_summary=f"Director operation: {operation.operation}",
        )
        return DirectorToolResult(
            ok=True,
            data={
                "revision_id": str(revision.id),
                "revision_number": revision.revision_number,
                "operation": operation.operation,
            },
        )

    @staticmethod
    def _remove_if_allowed(item: TimelineItem, item_id: uuid.UUID) -> bool:
        if item.id != item_id:
            return True
        if item.locked_by_user:
            raise DirectorToolError("USER_LOCKED_ITEM", "Director cannot remove a user-locked item")
        return False

    async def _set_layout(self, parsed: SetLayoutOperation) -> DirectorToolResult:
        timeline = await self._timeline()
        item = next((item for item in timeline.items if item.id == parsed.timeline_item_id), None)
        if item is None:
            raise DirectorToolError("TIMELINE_ITEM_NOT_FOUND", "Timeline item not found")
        if item.locked_by_user:
            raise DirectorToolError("USER_LOCKED_ITEM", "Director cannot change a user-locked item")
        item.layout = parsed.layout
        revision = await self.revisions.create(
            self.production_project_id, timeline, change_summary="Director layout change"
        )
        return DirectorToolResult(ok=True, data={"revision_id": str(revision.id)})

    async def _set_transition(self, parsed: "TransitionArguments") -> DirectorToolResult:
        timeline = await self._timeline()
        item = next((item for item in timeline.items if item.id == parsed.timeline_item_id), None)
        if item is None:
            raise DirectorToolError("TIMELINE_ITEM_NOT_FOUND", "Timeline item not found")
        item.metadata["transition"] = {"name": parsed.transition, "duration": parsed.duration}
        revision = await self.revisions.create(
            self.production_project_id, timeline, change_summary="Director transition change"
        )
        return DirectorToolResult(ok=True, data={"revision_id": str(revision.id)})

    async def _find(self, name: str, parsed: Any) -> DirectorToolResult:
        if name == "find_clip":
            asset = await self._asset(parsed.asset_id)
            clip_candidates = ClipFinder().find(
                asset, parsed.description, preferred_duration=parsed.preferred_duration
            )
            return DirectorToolResult(
                ok=True,
                data={"candidates": [candidate.as_dict() for candidate in clip_candidates]},
            )
        else:
            context = await self.context()
            query = parsed.description.casefold()
            asset_candidates: list[dict[str, Any]] = []
            for item in context["assets"]:
                text = " ".join(
                    [
                        str(item.get("title", "")),
                        str(item.get("description", "")),
                        " ".join(item.get("tags", [])),
                    ]
                ).casefold()
                score = 0.1 + 0.8 * len(set(query.split()) & set(text.split())) / max(
                    1, len(set(query.split()))
                )
                asset_candidates.append(
                    {
                        "asset_id": item["id"],
                        "score": round(min(1.0, score), 4),
                        "reason": "metadata and lexical match",
                    }
                )
            asset_candidates.sort(key=lambda row: row["score"], reverse=True)
            return DirectorToolResult(
                ok=True,
                data={
                    "candidates": asset_candidates[:5],
                    "selection_required": name == "find_visual_candidates",
                },
            )

    async def _validate(self) -> DirectorToolResult:
        timeline = await self._timeline()
        profile = await self._profile()
        report = self.validator.validate(timeline, profile)
        return DirectorToolResult(
            ok=report.ok,
            data=report.as_dict(),
            error=None
            if report.ok
            else {
                "code": "TIMELINE_INVALID",
                "message": "Deterministic validation failed",
                "recoverable": True,
            },
        )

    async def _render(
        self, *, profile_name: str, start: float | None, end: float | None
    ) -> DirectorToolResult:
        if profile_name == "preview":
            current = await self.session.scalar(
                select(DirectorRun).where(
                    DirectorRun.production_project_id == self.production_project_id,
                    DirectorRun.active.is_(True),
                )
            )
            if current and current.preview_count >= self.limits.max_preview_renders:
                raise DirectorToolError("PREVIEW_LIMIT_REACHED", "Maximum preview renders reached")
            if current:
                current.preview_count += 1
        video = await ProductionRenderService(
            self.session, LocalStorage(self.settings.media_root), self.settings
        ).render(self.production_project_id, profile_name=profile_name)
        path = video.preview_path if profile_name == "preview" else video.final_path
        return DirectorToolResult(
            ok=True,
            data={
                "video_project_id": str(video.id),
                "profile": profile_name,
                "path": path,
                "start": start,
                "end": end,
            },
        )

    async def _inspect_render(self) -> DirectorToolResult:
        production = await self.session.get(ProductionProject, self.production_project_id)
        video = (
            await self.session.get(VideoProject, production.active_video_project_id)
            if production and production.active_video_project_id
            else None
        )
        if video is None:
            return DirectorToolResult(ok=True, data={"rendered": False})
        return DirectorToolResult(
            ok=True,
            data={
                "rendered": True,
                "preview_available": bool(video.preview_path),
                "final_available": bool(video.final_path),
                "metrics": video.metrics or {},
            },
        )

    async def _undo(self, revision_id: uuid.UUID | None) -> DirectorToolResult:
        history = await self.revisions.history(self.production_project_id)
        chosen = revision_id or (history[-2].id if len(history) > 1 else None)
        if chosen is None:
            raise DirectorToolError("NO_REVISION_TO_UNDO", "No previous revision exists")
        revision = await self.revisions.rollback(self.production_project_id, chosen)
        return DirectorToolResult(
            ok=True,
            data={"revision_id": str(revision.id), "revision_number": revision.revision_number},
        )

    async def _create_variant(self, parsed: VariantRequest) -> DirectorToolResult:
        active = await self.revisions.active(self.production_project_id)
        run = await self.session.scalar(
            select(DirectorRun)
            .where(
                DirectorRun.production_project_id == self.production_project_id,
                DirectorRun.active.is_(True),
            )
            .order_by(DirectorRun.created_at.desc())
        )
        if run is None:
            raise DirectorToolError("DIRECTOR_RUN_NOT_FOUND", "An active Director run is required")
        keys = []
        for index in range(parsed.count):
            key = f"{run.variant_count + index + 1}"
            self.session.add(
                DirectorVariant(
                    run_id=run.id,
                    base_revision_id=active.id,
                    variant_key=key,
                    start=parsed.start,
                    end=parsed.end,
                    goal=parsed.goal,
                    timeline_json=active.timeline_json,
                    quality_json={},
                    selected=False,
                )
            )
            keys.append(key)
        run.variant_count += parsed.count
        await self.session.commit()
        return DirectorToolResult(
            ok=True, data={"variant_keys": keys, "active_revision_id": str(active.id)}
        )

    async def _compare_revisions(self, parsed: "CompareRevisionsArguments") -> DirectorToolResult:
        left = await self.session.get(TimelineRevision, parsed.from_revision)
        right = await self.session.get(TimelineRevision, parsed.to_revision)
        if left is None or right is None:
            raise DirectorToolError("REVISION_NOT_FOUND", "Revision not found")
        if (
            left.production_project_id != self.production_project_id
            or right.production_project_id != self.production_project_id
        ):
            raise DirectorToolError(
                "REVISION_OUTSIDE_PROJECT", "Revision is outside the runtime project"
            )
        left_items = {str(item.get("id")): item for item in left.timeline_json.get("items", [])}
        right_items = {str(item.get("id")): item for item in right.timeline_json.get("items", [])}
        changed = [
            (float(right_items[item_id].get("start", 0)), float(right_items[item_id].get("end", 0)))
            for item_id in left_items.keys() & right_items.keys()
            if left_items[item_id] != right_items[item_id]
        ]
        diff = RevisionDiff(
            from_revision=left.id,
            to_revision=right.id,
            changed_ranges=changed,
            added_items=list(right_items.keys() - left_items.keys()),
            removed_items=list(left_items.keys() - right_items.keys()),
        )
        return DirectorToolResult(ok=True, data=diff.model_dump(mode="json"))

    async def _timeline(self) -> ProductionTimeline:
        production = await self.session.get(ProductionProject, self.production_project_id)
        if production is None:
            raise NotFoundError("ProductionProject not found")
        if production.active_timeline_revision_id:
            revision = await self.session.get(
                TimelineRevision, production.active_timeline_revision_id
            )
            if revision:
                return ProductionTimeline.model_validate(revision.timeline_json)
        if not production.primary_voiceover_id:
            raise InvalidStateError("A ready voiceover is required for Director runtime")
        voiceover = await self.session.get(VoiceoverTrack, production.primary_voiceover_id)
        if voiceover is None or voiceover.status not in {
            VoiceoverStatus.READY,
            VoiceoverStatus.REPLACED,
        }:
            raise InvalidStateError("A ready voiceover is required for Director runtime")
        return ProductionTimeline(
            duration=voiceover.duration,
            voiceover_track_id=voiceover.id,
            items=[
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
                    metadata={"source": "voiceover.words", "role": "subtitle"},
                ),
            ],
        )

    async def _asset(self, asset_id: uuid.UUID) -> VisualAsset:
        asset = await self.session.get(VisualAsset, asset_id)
        production = await self.session.get(ProductionProject, self.production_project_id)
        if asset is None or production is None or asset.project_id != production.project_id:
            raise DirectorToolError(
                "ASSET_OUTSIDE_PROJECT", "Asset does not belong to this production project"
            )
        return asset

    async def _profile(self) -> OutputProfile:
        context = await self.context()
        return OutputProfile.model_validate(context["platform"])

    def _text_boxes(self, timeline: ProductionTimeline):
        from app.editing.layout import TextBox

        boxes = []
        for item in timeline.items:
            data = item.metadata.get("text_layout")
            if item.track == TimelineTrack.TEXT and isinstance(data, dict):
                boxes.append(
                    TextBox(
                        int(data.get("x", 0)),
                        int(data.get("y", 0)),
                        int(data.get("width", 0)),
                        int(data.get("height", 0)),
                        int(data.get("font_size", 52)),
                        item.text or "",
                        str(data.get("anchor", "auto")),
                    )
                )
        return boxes


class DirectorRunService:
    """Creates runs and enforces one active run per ProductionProject."""

    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or Settings()

    async def start(
        self,
        production_project_id: uuid.UUID,
        instruction: str,
        *,
        profile_name: str | None = None,
    ) -> DirectorRun:
        production = await self.session.get(ProductionProject, production_project_id)
        if production is None:
            raise NotFoundError("ProductionProject not found")
        active = await self.session.scalar(
            select(DirectorRun).where(
                DirectorRun.production_project_id == production_project_id,
                DirectorRun.active.is_(True),
            )
        )
        if active is not None:
            raise InvalidStateError("A Director run is already active for this production")
        context = await DirectorContextBuilder(self.session, self.settings).build(
            production_project_id, profile_name=profile_name
        )
        run = DirectorRun(
            production_project_id=production_project_id,
            status="queued",
            instruction=instruction,
            context_json=context,
            history_json=[],
        )
        self.session.add(run)
        await self.session.commit()
        await self.session.refresh(run)
        return run

    async def get(self, run_id: uuid.UUID) -> DirectorRun:
        run = await self.session.get(DirectorRun, run_id)
        if run is None:
            raise NotFoundError("Director run not found")
        return run

    async def status(self, production_project_id: uuid.UUID) -> DirectorRun | None:
        return await self.session.scalar(
            select(DirectorRun)
            .where(DirectorRun.production_project_id == production_project_id)
            .order_by(DirectorRun.created_at.desc())
        )


class AssetIdArguments(BaseModel):
    asset_id: uuid.UUID


class FindVisualsArguments(BaseModel):
    description: str
    start: float = 0
    end: float | None = None


class FindClipArguments(BaseModel):
    asset_id: uuid.UUID
    description: str
    preferred_duration: float = 4.0


class PreviewArguments(BaseModel):
    start: float | None = None
    end: float | None = None


class UndoArguments(BaseModel):
    revision_id: uuid.UUID | None = None


class CompareRevisionsArguments(BaseModel):
    from_revision: uuid.UUID
    to_revision: uuid.UUID


class TransitionArguments(BaseModel):
    timeline_item_id: uuid.UUID
    transition: str
    duration: float = 0.25
