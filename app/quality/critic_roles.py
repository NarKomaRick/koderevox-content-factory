"""Independent, bounded critic roles for autonomous review."""

from collections import Counter
from typing import Any, Protocol

from app.core.config import Settings
from app.director.schemas import (
    AggregatedReview,
    CriticProblem,
    CriticReport,
    DirectorPlan,
    OutputProfile,
    StoryAnalysis,
)
from app.editing.layout import LayoutEngine
from app.editing.validation import TimelineValidator
from app.models.enums import TimelineTrack
from app.quality.visual_critic import DeterministicVisualCritic
from app.schemas.production import ProductionTimeline


class CriticRole(Protocol):
    name: str

    def evaluate(
        self,
        timeline: ProductionTimeline,
        profile: OutputProfile,
        *,
        story: StoryAnalysis | None = None,
        plan: DirectorPlan | None = None,
        audio: dict[str, Any] | None = None,
        preview: dict[str, Any] | None = None,
    ) -> CriticReport: ...


def _problem(
    role: str,
    index: int,
    start: float,
    end: float,
    kind: str,
    description: str,
    *,
    hard: bool = False,
    severity: str = "medium",
) -> CriticProblem:
    return CriticProblem(
        id=f"{role}-{index}",
        start=start,
        end=end,
        kind=kind,
        description=description,
        hard=hard,
        severity=severity,
    )


class VisualCritic:
    name = "visual"

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.base = DeterministicVisualCritic(self.settings)

    def evaluate(
        self,
        timeline: ProductionTimeline,
        profile: OutputProfile,
        *,
        story=None,
        plan=None,
        audio=None,
        preview=None,
    ) -> CriticReport:
        base = self.base.evaluate(timeline, profile)
        problems = [
            _problem(
                self.name,
                index,
                float(item.get("time") or item.get("start") or 0),
                float(item.get("time") or item.get("end") or 0),
                str(item.get("code") or item.get("type") or "visual_issue"),
                str(item.get("message") or item.get("description") or "Visual issue"),
                hard=str(item.get("code", "")).startswith(("TEXT_", "MISSING_")),
            )
            for index, item in enumerate(base.get("problems", []), 1)
        ]
        for index, item in enumerate(timeline.items, len(problems) + 1):
            if (
                item.track
                in {
                    TimelineTrack.BROLL,
                    TimelineTrack.VIDEO_BASE,
                    TimelineTrack.OVERLAY,
                    TimelineTrack.GRAPHICS,
                }
                and "visual_intent" not in item.metadata
            ):
                problems.append(
                    _problem(
                        self.name,
                        index,
                        item.start,
                        item.end,
                        "missing_visual_intent",
                        "Major visual has no concise purpose or reason.",
                        severity="low",
                    )
                )
        score = max(
            0.0,
            min(
                10.0,
                float(base.get("composition", 5.0)) - sum(problem.hard for problem in problems),
            ),
        )
        return CriticReport(
            role="visual",
            score=round(score, 2),
            problems=problems,
            signals={"preview_available": bool(preview)},
        )


class StoryCritic:
    name = "story"

    def evaluate(
        self,
        timeline: ProductionTimeline,
        profile: OutputProfile,
        *,
        story=None,
        plan=None,
        audio=None,
        preview=None,
    ) -> CriticReport:
        problems: list[CriticProblem] = []
        beats = story.beats if story else []
        visuals = [
            item
            for item in timeline.items
            if item.track
            in {
                TimelineTrack.VIDEO_BASE,
                TimelineTrack.BROLL,
                TimelineTrack.GRAPHICS,
                TimelineTrack.TEXT,
            }
        ]
        for index, beat in enumerate(beats, 1):
            supported = [
                item for item in visuals if item.start < beat.end and item.end > beat.start
            ]
            purposeful = [
                item
                for item in supported
                if isinstance(item.metadata.get("visual_intent"), dict)
                and item.metadata["visual_intent"].get("reason")
            ]
            if beat.visual_need == "high" and not purposeful:
                problems.append(
                    _problem(
                        self.name,
                        index,
                        beat.start,
                        beat.end,
                        "story_support",
                        "A high-need story beat has no justified visual support.",
                        severity="high",
                    )
                )
        score = max(0.0, 10.0 - len(problems) * 1.8)
        return CriticReport(
            role="story",
            score=round(score, 2),
            problems=problems,
            signals={
                "beats": len(beats),
                "supported_beats": sum(
                    bool(
                        [
                            item
                            for item in visuals
                            if item.start < beat.end and item.end > beat.start
                        ]
                    )
                    for beat in beats
                ),
            },
        )


class ContinuityCritic:
    name = "continuity"

    def evaluate(
        self,
        timeline: ProductionTimeline,
        profile: OutputProfile,
        *,
        story=None,
        plan=None,
        audio=None,
        preview=None,
    ) -> CriticReport:
        visuals = [
            item
            for item in timeline.items
            if item.track
            in {
                TimelineTrack.VIDEO_BASE,
                TimelineTrack.BROLL,
                TimelineTrack.OVERLAY,
                TimelineTrack.GRAPHICS,
            }
        ]
        asset_counts = Counter(str(item.asset_id) for item in visuals if item.asset_id)
        layout_counts = Counter(item.layout for item in visuals)
        problems = []
        for index, (asset_id, count) in enumerate(asset_counts.items(), 1):
            if count >= 3:
                problems.append(
                    _problem(
                        self.name,
                        index,
                        0,
                        timeline.duration,
                        "asset_fatigue",
                        (
                            f"Asset {asset_id} is reused {count} times; review whether "
                            "repetition is purposeful."
                        ),
                        severity="low",
                    )
                )
        if len(layout_counts) > 4:
            problems.append(
                _problem(
                    self.name,
                    len(problems) + 1,
                    0,
                    timeline.duration,
                    "style_jump",
                    "Many layout modes are used; check visual language consistency.",
                    severity="medium",
                )
            )
        return CriticReport(
            role="continuity",
            score=round(max(0.0, 10 - len(problems) * 1.2), 2),
            problems=problems,
            signals={"asset_usage": dict(asset_counts), "layout_usage": dict(layout_counts)},
        )


class PacingCritic:
    name = "pacing"

    def evaluate(
        self,
        timeline: ProductionTimeline,
        profile: OutputProfile,
        *,
        story=None,
        plan=None,
        audio=None,
        preview=None,
    ) -> CriticReport:
        problems: list[CriticProblem] = []
        if story:
            for index, beat in enumerate(story.beats, 1):
                duration = beat.end - beat.start
                if duration > 12 and beat.visual_need == "high":
                    problems.append(
                        _problem(
                            self.name,
                            index,
                            beat.start,
                            beat.end,
                            "long_hold",
                            "A high-need beat holds for a long time; consider a purposeful "
                            "internal progression, not automatic cuts.",
                            severity="low",
                        )
                    )
        if audio:
            for index, pause in enumerate(audio.get("pauses", []), len(problems) + 1):
                if pause.get("kind") == "long" and not any(
                    item.start <= pause.get("start", 0) <= item.end
                    for item in timeline.items
                    if item.track in {TimelineTrack.GRAPHICS, TimelineTrack.TEXT}
                ):
                    problems.append(
                        _problem(
                            self.name,
                            index,
                            float(pause.get("start", 0)),
                            float(pause.get("end", 0)),
                            "unused_pause",
                            "A long pause may be a natural place for a hold or "
                            "explanatory graphic.",
                            severity="low",
                        )
                    )
        return CriticReport(
            role="pacing",
            score=round(max(0.0, 10 - len(problems) * 0.8), 2),
            problems=problems,
            signals={"pause_signals": len(audio.get("pauses", [])) if audio else 0},
        )


class TechnicalValidator:
    name = "technical"

    def __init__(self, settings: Settings | None = None) -> None:
        settings = settings or Settings()
        self.validator = TimelineValidator(LayoutEngine(font_path=settings.video_font_path))

    def evaluate(
        self,
        timeline: ProductionTimeline,
        profile: OutputProfile,
        *,
        story=None,
        plan=None,
        audio=None,
        preview=None,
    ) -> CriticReport:
        report = self.validator.validate(timeline, profile)
        problems = [
            _problem(
                self.name,
                index,
                issue.time or 0,
                issue.time or 0,
                issue.code,
                issue.message,
                hard=not issue.recoverable,
                severity="severe" if not issue.recoverable else "medium",
            )
            for index, issue in enumerate(report.issues, 1)
        ]
        if not any(item.track == TimelineTrack.AUDIO_MASTER for item in timeline.items):
            problems.append(
                _problem(
                    self.name,
                    len(problems) + 1,
                    0,
                    timeline.duration,
                    "missing_audio",
                    "Timeline has no master voiceover track.",
                    hard=True,
                    severity="severe",
                )
            )
        return CriticReport(
            role="technical",
            score=10.0 if not problems else max(0.0, 10 - len(problems) * 2),
            problems=problems,
            signals={"hard_failures": sum(problem.hard for problem in problems)},
        )


class ReviewAggregator:
    def __init__(
        self, roles: list[CriticRole] | None = None, settings: Settings | None = None
    ) -> None:
        settings = settings or Settings()
        self.roles = roles or [
            VisualCritic(settings),
            StoryCritic(),
            ContinuityCritic(),
            PacingCritic(),
            TechnicalValidator(settings),
        ]

    def evaluate(
        self,
        timeline: ProductionTimeline,
        profile: OutputProfile,
        *,
        story=None,
        plan=None,
        audio=None,
        preview=None,
        previous: AggregatedReview | None = None,
    ) -> AggregatedReview:
        reports = [
            role.evaluate(timeline, profile, story=story, plan=plan, audio=audio, preview=preview)
            for role in self.roles
        ]
        problems = [problem for report in reports for problem in report.problems]
        hard = [problem for problem in problems if problem.hard]
        critical = [problem for problem in problems if problem.severity in {"high", "severe"}]
        score = round(sum(report.score for report in reports) / max(1, len(reports)), 2)
        previous_score = previous.overall_score if previous else score
        return AggregatedReview(
            overall_score=score,
            hard_failures=hard,
            critical_problems=critical,
            reports=reports,
            quality_changes={"overall_score": round(score - previous_score, 2)},
            early_exit=not hard and not critical and score >= 8.0,
        )
