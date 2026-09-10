"""Hard, deterministic checks applied before a Director finalizes a timeline."""

from dataclasses import dataclass
from typing import Any

from app.director.schemas import OutputProfile
from app.editing.layout import LayoutEngine, TextBox
from app.models.enums import TimelineTrack
from app.schemas.production import ProductionTimeline


@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    time: float | None = None
    elements: tuple[str, ...] = ()
    recoverable: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "time": self.time,
            "elements": list(self.elements),
            "recoverable": self.recoverable,
        }


@dataclass(frozen=True)
class ValidationReport:
    ok: bool
    issues: tuple[ValidationIssue, ...]

    def as_dict(self) -> dict[str, Any]:
        return {"ok": self.ok, "issues": [issue.as_dict() for issue in self.issues]}


class TextLayoutValidator:
    def __init__(self, layout: LayoutEngine) -> None:
        self.layout = layout

    def validate(
        self, timeline: ProductionTimeline, profile: OutputProfile
    ) -> list[ValidationIssue]:
        text_items = [item for item in timeline.items if item.track == TimelineTrack.TEXT]
        boxes: list[tuple[Any, TextBox]] = []
        issues: list[ValidationIssue] = []
        for item in text_items:
            metadata = item.metadata
            box_data = metadata.get("text_layout")
            if not isinstance(box_data, dict):
                box = self.layout.place(
                    item.text or "",
                    profile,
                    anchor=str(metadata.get("anchor", "auto")),  # type: ignore[arg-type]
                    font_size=int(metadata.get("font_size", 52)),
                    occupied=[existing for _, existing in boxes],
                )
            else:
                box = TextBox(
                    int(box_data.get("x", 0)),
                    int(box_data.get("y", 0)),
                    int(box_data.get("width", 0)),
                    int(box_data.get("height", 0)),
                    int(box_data.get("font_size", 0)),
                    str(item.text or ""),
                    str(box_data.get("anchor", "auto")),
                )
            element_id = str(item.id)
            boxes.append((item, box))
            if box.x < 0 or box.y < 0 or box.right > profile.width or box.bottom > profile.height:
                issues.append(
                    ValidationIssue(
                        "TEXT_OUTSIDE_CANVAS",
                        "Text box is outside canvas",
                        item.start,
                        (element_id,),
                        False,
                    )
                )
            safe = profile.safe_zones
            if (
                box.x < safe.left
                or box.right > profile.width - safe.right
                or box.y < safe.top
                or box.bottom > profile.height - safe.bottom
            ):
                issues.append(
                    ValidationIssue(
                        "TEXT_IN_FORBIDDEN_ZONE",
                        "Text box crosses a platform safe zone",
                        item.start,
                        (element_id,),
                        False,
                    )
                )
            if box.font_size < 28:
                issues.append(
                    ValidationIssue(
                        "TEXT_TOO_SMALL",
                        "Text font is below readability minimum",
                        item.start,
                        (element_id,),
                        False,
                    )
                )
            if item.end - item.start < 0.6:
                issues.append(
                    ValidationIssue(
                        "TEXT_TOO_BRIEF",
                        "Text is displayed too briefly to read",
                        item.start,
                        (element_id,),
                    )
                )
            for other_item, other_box in boxes[:-1]:
                if (
                    item.start < other_item.end
                    and other_item.start < item.end
                    and self.layout.overlaps(box, other_box)
                ):
                    code = (
                        "TEXT_SUBTITLE_COLLISION"
                        if other_item.metadata.get("role") == "subtitle"
                        else "TEXT_TEXT_COLLISION"
                    )
                    issues.append(
                        ValidationIssue(
                            code,
                            "Overlapping text boxes",
                            max(item.start, other_item.start),
                            (str(other_item.id), element_id),
                            False,
                        )
                    )
        return issues


class TimelineValidator:
    def __init__(self, layout: LayoutEngine) -> None:
        self.text = TextLayoutValidator(layout)

    def validate(self, timeline: ProductionTimeline, profile: OutputProfile) -> ValidationReport:
        issues: list[ValidationIssue] = []
        if timeline.duration > profile.max_duration + 0.05:
            issues.append(
                ValidationIssue(
                    "DURATION_EXCEEDS_PROFILE",
                    "Timeline exceeds output profile duration",
                    timeline.duration,
                    recoverable=False,
                )
            )
        for item in timeline.items:
            if item.end > timeline.duration + 0.05:
                issues.append(
                    ValidationIssue(
                        "INVALID_TIMELINE_RANGE",
                        "Timeline item exceeds master duration",
                        item.start,
                        (str(item.id),),
                        False,
                    )
                )
            if (
                item.asset_id is None
                and item.track
                in {TimelineTrack.BROLL, TimelineTrack.OVERLAY, TimelineTrack.VIDEO_BASE}
                and not item.text
                and not item.metadata.get("blur")
            ):
                issues.append(
                    ValidationIssue(
                        "MISSING_REFERENCED_ASSET",
                        "Visual item has no asset reference",
                        item.start,
                        (str(item.id),),
                        False,
                    )
                )
        issues.extend(self.text.validate(timeline, profile))
        return ValidationReport(not issues, tuple(issues))
