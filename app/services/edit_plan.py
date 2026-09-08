import re
from collections.abc import Sequence
from typing import Any

from app.schemas.processing import TranscriptSegment
from app.schemas.video import EditPlan
from app.services.errors import InvalidStateError


def normalize_phrase(value: str) -> str:
    return " ".join(re.findall(r"\w+", value.casefold(), flags=re.UNICODE))


class EditPlanValidator:
    def __init__(
        self,
        *,
        minimum_duration: float = 5,
        maximum_duration: float = 75,
        boundary_tolerance: float = 0.25,
    ) -> None:
        self.minimum_duration = minimum_duration
        self.maximum_duration = maximum_duration
        self.boundary_tolerance = boundary_tolerance

    def validate(
        self,
        plan: EditPlan,
        *,
        source_duration: float,
        transcript_segments: Sequence[dict[str, Any]],
        require_speech_boundaries: bool = False,
    ) -> EditPlan:
        segments = [TranscriptSegment.model_validate(item) for item in transcript_segments]
        if not segments:
            raise InvalidStateError("Video source has no timestamped transcript segments")
        for clip in plan.clips:
            if clip.source_end > source_duration + self.boundary_tolerance:
                raise InvalidStateError("Clip ends after source duration")
            try:
                referenced = [segments[index] for index in clip.source_segment_ids]
            except IndexError as exc:
                raise InvalidStateError("Clip references a nonexistent transcript segment") from exc
            if min(clip.source_segment_ids) < 0:
                raise InvalidStateError("Negative transcript segment ID")
            span_start = min(segment.start for segment in referenced)
            span_end = max(segment.end for segment in referenced)
            if clip.source_start < span_start - self.boundary_tolerance:
                raise InvalidStateError("Clip starts outside referenced transcript segments")
            if clip.source_end > span_end + self.boundary_tolerance:
                raise InvalidStateError("Clip ends outside referenced transcript segments")
            if not any(
                clip.source_start < segment.end and clip.source_end > segment.start
                for segment in referenced
            ):
                raise InvalidStateError("Clip does not intersect a transcript segment")
            actual_ids = {
                index
                for index, segment in enumerate(segments)
                if clip.source_start < segment.end and clip.source_end > segment.start
            }
            if actual_ids != set(clip.source_segment_ids):
                raise InvalidStateError(
                    "Clip must reference every transcript segment intersecting its range"
                )
            if require_speech_boundaries:
                boundaries = {
                    value
                    for segment in referenced
                    for value in (
                        segment.start,
                        segment.end,
                        *(word.start for word in segment.words),
                        *(word.end for word in segment.words),
                    )
                }
                if not any(
                    abs(clip.source_start - boundary) <= self.boundary_tolerance
                    for boundary in boundaries
                ) or not any(
                    abs(clip.source_end - boundary) <= self.boundary_tolerance
                    for boundary in boundaries
                ):
                    raise InvalidStateError("AI clip boundary would cut through a spoken word")
        total = sum(clip.source_end - clip.source_start for clip in plan.clips)
        if total < self.minimum_duration:
            raise InvalidStateError("Edit plan is too short")
        if total > self.maximum_duration:
            raise InvalidStateError("Edit plan exceeds configured maximum duration")
        selected_text = " ".join(
            segments[index].text
            for clip in plan.clips
            for index in clip.source_segment_ids
            if 0 <= index < len(segments)
        )
        normalized_transcript = normalize_phrase(selected_text)
        for emphasis in plan.emphasis:
            if normalize_phrase(emphasis.text) not in normalized_transcript:
                raise InvalidStateError("Emphasis text is not present in selected speech")
            if emphasis.end > total + self.boundary_tolerance:
                raise InvalidStateError("Emphasis extends past output duration")
        return plan.model_copy(update={"recommended_duration": round(total, 3)})

    def segment_ids_for_range(
        self,
        start: float,
        end: float,
        transcript_segments: Sequence[dict[str, Any]],
    ) -> list[int]:
        ids = [
            index
            for index, raw in enumerate(transcript_segments)
            if start < float(raw["end"]) and end > float(raw["start"])
        ]
        if not ids:
            raise InvalidStateError("Selected range has no spoken transcript")
        return ids
