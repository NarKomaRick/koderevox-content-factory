"""Phase 7 orchestration layered on top of the Phase 6 executor."""

import time
import uuid
from pathlib import Path
from typing import Any

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider
from app.assets.ranking import VisualCandidateRanker
from app.audio_intelligence.analyzer import AudioIntelligenceAnalyzer
from app.core.config import Settings
from app.director.multimodal import PreviewPacketBuilder
from app.director.planner import DeterministicDirectorPlanner, StructuredDirectorPlanner
from app.director.preferences import DirectorPreferences
from app.director.review import (
    CorrectionPlanner,
    DeterministicDirectorReviewer,
    StructuredDirectorReviewer,
)
from app.director.runtime import DirectorRuntime
from app.director.schemas import DirectorPlan, OutputProfile, StoryAnalysis
from app.director.story import DeterministicStoryAnalyst, StructuredStoryAnalyst
from app.models import DirectorRun, ProductionProject, VideoProject, VoiceoverTrack
from app.models.enums import AssetType, VoiceoverStatus
from app.progress import ProgressReporter
from app.quality.critic_roles import ReviewAggregator
from app.storage.local import LocalStorage

logger = structlog.get_logger()


class AutonomousDirector:
    """Runs story → plan → rough cut → review → correction → final with hard bounds."""

    def __init__(
        self,
        session: AsyncSession,
        production_project_id: uuid.UUID,
        settings: Settings,
        provider: AIProvider | None = None,
    ) -> None:
        self.session = session
        self.production_project_id = production_project_id
        self.settings = settings
        self.provider = provider
        self.runtime = DirectorRuntime(session, production_project_id, settings)
        self.audio = AudioIntelligenceAnalyzer()
        self.ranker = VisualCandidateRanker()
        self.review_aggregator = ReviewAggregator(settings=settings)
        self.preferences = DirectorPreferences(session)

    def _progress(self, run: DirectorRun) -> ProgressReporter:
        return ProgressReporter(
            self.session,
            "director",
            run.id,
            source_kind="fake" if self.settings.ai_provider == "mock" else "production",
            director_run_id=run.id,
            production_project_id=run.production_project_id,
            min_delta=self.settings.progress_min_percent_delta,
            min_interval_seconds=self.settings.progress_update_interval_seconds,
        )

    async def _stage(self, run: DirectorRun, status: str, message: str) -> None:
        run.status = status
        await self._progress(run).report_stage(
            status,
            step_index=run.step_count,
            step_total=self.settings.director_max_steps,
            message=message,
            force=True,
        )

    async def run(self, run: DirectorRun, *, render: bool = True) -> DirectorRun:
        started = time.monotonic()
        run.active = True
        await self._stage(run, "analyzing_story", "Анализирую историю")
        run.director_iteration += 1
        await self.session.commit()
        try:
            context = await self.runtime.context()
            story = await self._story(context, run.instruction)
            run.story_analysis_json = story.model_dump(mode="json")
            await self.session.commit()
            await logger.ainfo("story_analysis_created", run_id=str(run.id), beats=len(story.beats))

            await self._stage(run, "planning", "Планирую постановку")
            audio = await self._audio(context)
            run.audio_intelligence_json = audio
            plan = await self._plan(context, story, audio, run.instruction)
            run.director_plan_json = plan.model_dump(mode="json")
            await self.session.commit()
            await logger.ainfo("director_plan_created", run_id=str(run.id), beats=len(plan.beats))

            await self._stage(run, "assembling", "Собираю rough cut")
            await self._rough_cut(run, context, plan)
            rough = await self.runtime._timeline()
            run.current_revision_id = (
                await self.runtime.revisions.active(self.production_project_id)
            ).id
            run.metrics_json = {"rough_items": len(rough.items)}
            await self.session.commit()

            await self._stage(run, "reviewing", "Проверяю монтаж")
            review = await self._review(run, context, rough, story, plan, audio, render=render)
            run.quality_report_json = review.model_dump(mode="json")
            run.review_iterations = 1
            await self.session.commit()
            await logger.ainfo(
                "director_review_completed", run_id=str(run.id), score=review.overall_score
            )

            if (
                review.hard_failures
                and run.review_iterations < self.settings.director_max_review_iterations
            ):
                await self._stage(run, "correcting", "Исправляю найденное")
                await self._apply_safe_corrections(run, review)
                corrected = await self.runtime._timeline()
                review = self.review_aggregator.evaluate(
                    corrected,
                    await self._profile(),
                    story=story,
                    plan=plan,
                    audio=audio,
                )
                run.quality_report_json = review.model_dump(mode="json")
                run.review_iterations += 1
                await logger.ainfo(
                    "quality_improved", run_id=str(run.id), score=review.overall_score
                )

            if review.hard_failures:
                raise RuntimeError("Hard Director validation failures remain")
            if render:
                await self._stage(run, "finalizing", "Финализирую видео")
                final_result = await self.runtime.execute(
                    "finalize", {}, run=run, step=run.step_count + 1
                )
                if not final_result.ok:
                    raise RuntimeError(final_result.error or {"code": "FINAL_RENDER_FAILED"})
            run.status = "completed"
            run.active = False
            run.best_revision_id = run.current_revision_id
            run.metrics_json = {
                **(run.metrics_json or {}),
                "llm_calls": run.llm_call_count,
                "tool_calls": run.step_count,
                "preview_renders": run.preview_count,
                "review_iterations": run.review_iterations,
                "critic_calls": run.review_iterations * len(self.review_aggregator.roles),
                "variants": run.variant_count,
                "runtime_seconds": round(time.monotonic() - started, 3),
                "final_render": "not_tested" if not render else "requested",
            }
            await self.session.commit()
            await self._progress(run).complete(message="Director завершил работу")
            await logger.ainfo("director_completed", run_id=str(run.id), status=run.status)
            return run
        except Exception as exc:
            run.status = "failed"
            run.active = False
            run.error = str(exc)[:2000]
            run.metrics_json = {
                **(run.metrics_json or {}),
                "runtime_seconds": round(time.monotonic() - started, 3),
            }
            await self.session.commit()
            await self._progress(run).fail(error_code=type(exc).__name__, message=str(exc)[:2000])
            await logger.aerror(
                "director_completed",
                run_id=str(run.id),
                status=run.status,
                error_type=type(exc).__name__,
            )
            return run

    async def _story(self, context: dict[str, Any], instruction: str) -> StoryAnalysis:
        if self.provider is not None and self.settings.ai_provider != "mock":
            return await StructuredStoryAnalyst(self.provider).analyze(context, instruction)
        return await DeterministicStoryAnalyst().analyze(context, instruction)

    async def _plan(
        self, context: dict[str, Any], story: StoryAnalysis, audio: dict[str, Any], instruction: str
    ) -> DirectorPlan:
        if self.provider is not None and self.settings.ai_provider != "mock":
            return await StructuredDirectorPlanner(self.provider).plan(
                context, story, audio, instruction
            )
        return await DeterministicDirectorPlanner().plan(context, story, audio, instruction)

    async def _audio(self, context: dict[str, Any]) -> dict[str, Any]:
        production = await self.session.get(ProductionProject, self.production_project_id)
        voiceover = (
            await self.session.get(VoiceoverTrack, production.primary_voiceover_id)
            if production and production.primary_voiceover_id
            else None
        )
        if voiceover is None or voiceover.status not in {
            VoiceoverStatus.READY,
            VoiceoverStatus.REPLACED,
        }:
            return {
                "duration": 0,
                "windows": [],
                "pauses": [],
                "emphasis": [],
                "source": "voiceover_metadata",
            }
        path = LocalStorage(self.settings.media_root).resolve(voiceover.processed_path)
        return (await self.audio.analyze(voiceover, audio_path=path)).model_dump(mode="json")

    async def _rough_cut(
        self, run: DirectorRun, context: dict[str, Any], plan: DirectorPlan
    ) -> None:
        assets = list(context.get("assets", []))
        for index, beat in enumerate(plan.beats[: self.settings.director_max_steps]):
            if beat.end - beat.start < 0.6:
                continue
            candidates = self.ranker.rank(assets, beat.meaning)
            selected = candidates[0] if candidates and candidates[0]["score"] >= 0.12 else None
            if selected is not None:
                asset_id = uuid.UUID(str(selected["asset_id"]))
                visual_intent = {
                    "purpose": "explain" if beat.purpose == "explanation" else "emphasize",
                    "reason": f"Supports beat {beat.id}: {beat.meaning[:300]}",
                    "importance": beat.importance,
                }
                args: dict[str, Any] = {
                    "asset_id": str(asset_id),
                    "start": beat.start,
                    "end": beat.end,
                    "layout": "fullscreen",
                    "visual_intent": visual_intent,
                }
                if selected.get("type") == AssetType.VIDEO.value:
                    clip_result = await self.runtime.execute(
                        "find_clip",
                        {
                            "asset_id": str(asset_id),
                            "description": beat.meaning[:500],
                            "preferred_duration": min(4.0, beat.end - beat.start),
                        },
                        run=run,
                        step=index + 1,
                    )
                    candidates_for_clip = (
                        clip_result.data.get("candidates", []) if clip_result.ok else []
                    )
                    if candidates_for_clip:
                        clip = candidates_for_clip[0]
                        args.update({"source_start": clip["start"], "source_end": clip["end"]})
                result = await self.runtime.execute("add_visual", args, run=run, step=index + 1)
                if result.ok:
                    run.step_count += 1
                    continue
            graphic_result = await self.runtime.execute(
                "add_graphic",
                {
                    "kind": "simple_diagram" if beat.purpose == "explanation" else "title_card",
                    "start": beat.start,
                    "end": beat.end,
                    "content": {"title": beat.meaning[:160]},
                    "reason": f"No sufficiently relevant asset; a graphic carries beat {beat.id}.",
                },
                run=run,
                step=index + 1,
            )
            if graphic_result.ok:
                run.step_count += 1
        if plan.beats:
            beat = plan.beats[0]
            await self.runtime.execute(
                "add_text",
                {
                    "text": beat.meaning[:120] or "Главная мысль",
                    "start": beat.start,
                    "end": min(beat.end, beat.start + 3),
                    "anchor": "top_center",
                    "semantic_role": "headline",
                    "reason": "The opening headline states the story promise.",
                },
                run=run,
                step=run.step_count + 1,
            )
            run.step_count += 1

    async def _review(
        self,
        run: DirectorRun,
        context: dict[str, Any],
        timeline: Any,
        story: StoryAnalysis,
        plan: DirectorPlan,
        audio: dict[str, Any],
        *,
        render: bool,
    ):
        preview = None
        if render:
            result = await self.runtime.execute(
                "render_preview", {}, run=run, step=run.step_count + 1
            )
            if result.ok:
                video = await self.session.get(
                    VideoProject, uuid.UUID(str(result.data["video_project_id"]))
                )
                if video and video.preview_path:
                    preview_path = LocalStorage(self.settings.media_root).resolve(
                        video.preview_path
                    )
                    try:
                        preview = await PreviewPacketBuilder(
                            Path(self.settings.render_temp_root)
                        ).build(
                            preview_path,
                            timeline_summary=[
                                {"track": item.track.value, "start": item.start, "end": item.end}
                                for item in timeline.items
                            ],
                            voiceover_segments=list(
                                context.get("voiceover", {}).get("segments", [])
                            ),
                            beats=[item.model_dump(mode="json") for item in plan.beats],
                        )
                    except (FileNotFoundError, OSError, RuntimeError):
                        preview = {
                            "status": "not_tested",
                            "reason": "Preview frame extraction unavailable.",
                        }
        profile = await self._profile()
        review = self.review_aggregator.evaluate(
            timeline, profile, story=story, plan=plan, audio=audio, preview=preview
        )
        if self.provider is not None and self.settings.ai_provider != "mock":
            director_review = await StructuredDirectorReviewer(self.provider).review(
                review, {"story_analysis": story.model_dump(mode="json")}
            )
        else:
            director_review = await DeterministicDirectorReviewer().review(
                review, {"story_analysis": story.model_dump(mode="json")}
            )
        run.history_json = [
            *(run.history_json or []),
            {"stage": "review", "director_review": director_review.model_dump(mode="json")},
        ]
        return review

    async def _apply_safe_corrections(self, run: DirectorRun, review: Any) -> None:
        plan = CorrectionPlanner().from_review(review)
        run.history_json = [
            *(run.history_json or []),
            {"stage": "correction_plan", "plan": plan.model_dump(mode="json")},
        ]
        for problem in review.hard_failures[: self.settings.director_max_steps]:
            if problem.kind == "MISSING_REFERENCED_ASSET" and problem.elements:
                try:
                    await self.runtime.execute(
                        "remove_item",
                        {"timeline_item_id": problem.elements[0]},
                        run=run,
                        step=run.step_count + 1,
                    )
                    run.step_count += 1
                except (ValueError, TypeError):
                    continue

    async def _profile(self) -> OutputProfile:
        return OutputProfile.model_validate((await self.runtime.context())["platform"])
