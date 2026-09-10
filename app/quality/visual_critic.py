"""A bounded critic that reports problems and never edits timelines."""

from typing import Any

from app.core.config import Settings
from app.director.schemas import OutputProfile
from app.editing.layout import LayoutEngine
from app.editing.validation import TimelineValidator
from app.models.enums import TimelineTrack
from app.quality.scoring import quality_scores
from app.schemas.production import ProductionTimeline
from app.services.production_timeline import VisualGapAnalyzer


class DeterministicVisualCritic:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or Settings()
        self.validator = TimelineValidator(LayoutEngine(font_path=self.settings.video_font_path))

    def evaluate(self, timeline: ProductionTimeline, profile: OutputProfile) -> dict[str, Any]:
        validation = self.validator.validate(timeline, profile)
        gaps = VisualGapAnalyzer(self.settings).analyze(timeline)
        visual_count = sum(
            item.track
            in {
                TimelineTrack.VIDEO_BASE,
                TimelineTrack.BROLL,
                TimelineTrack.OVERLAY,
                TimelineTrack.GRAPHICS,
                TimelineTrack.TEXT,
            }
            for item in timeline.items
        )
        scores = quality_scores(
            visual_count=visual_count, issue_count=len(validation.issues), gap_count=len(gaps)
        )
        problems = [issue.as_dict() for issue in validation.issues]
        problems.extend(
            {
                "start": gap.start,
                "end": gap.end,
                "severity": "medium",
                "type": "visual_gap",
                "description": gap.reason,
            }
            for gap in gaps
        )
        return {
            **scores,
            "composition": max(0.0, 9.0 - len(validation.issues)),
            "visual_relevance": scores["visual_relevance"],
            "problems": problems,
        }
