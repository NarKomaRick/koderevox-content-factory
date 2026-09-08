import pytest
from pydantic import ValidationError

from app.schemas.video import EditClip, EditPlan
from app.services.edit_plan import EditPlanValidator
from app.services.errors import InvalidStateError

SEGMENTS = [
    {"start": 0.0, "end": 5.0, "text": "Мы нашли двойной запрос"},
    {"start": 5.0, "end": 10.0, "text": "REST API получил две записи"},
]


def plan(**updates) -> EditPlan:
    data = {
        "clips": [
            {
                "source_start": 0,
                "source_end": 5,
                "source_segment_ids": [0],
                "purpose": "hook",
            },
            {
                "source_start": 5,
                "source_end": 10,
                "source_segment_ids": [1],
                "purpose": "main",
            },
        ],
        "hook_text": "Двойной запрос",
        "emphasis": [{"start": 1, "end": 2, "text": "двойной запрос"}],
        "recommended_duration": 10,
        "reasoning_summary": "Цельный фрагмент",
        "framing": "center_crop",
        "pace": "medium",
    }
    data.update(updates)
    return EditPlan.model_validate(data)


def test_valid_edit_plan_uses_real_segments() -> None:
    validated = EditPlanValidator().validate(
        plan(), source_duration=10, transcript_segments=SEGMENTS
    )
    assert validated.recommended_duration == 10


def test_negative_timestamp_is_rejected() -> None:
    with pytest.raises(ValidationError):
        EditClip(
            source_start=-1,
            source_end=2,
            source_segment_ids=[0],
            purpose="hook",
        )


def test_overlapping_clips_are_rejected() -> None:
    clips = [
        {"source_start": 0, "source_end": 6, "source_segment_ids": [0, 1], "purpose": "hook"},
        {"source_start": 5, "source_end": 9, "source_segment_ids": [1], "purpose": "main"},
    ]
    with pytest.raises(ValidationError, match="overlap"):
        plan(clips=clips)


def test_end_after_duration_is_rejected() -> None:
    invalid = plan(
        clips=[
            {
                "source_start": 5,
                "source_end": 11,
                "source_segment_ids": [1],
                "purpose": "main",
            }
        ],
        emphasis=[],
    )
    with pytest.raises(InvalidStateError, match="source duration"):
        EditPlanValidator().validate(invalid, source_duration=10, transcript_segments=SEGMENTS)


def test_nonexistent_transcript_segment_is_rejected() -> None:
    invalid = plan(
        clips=[
            {
                "source_start": 0,
                "source_end": 5,
                "source_segment_ids": [99],
                "purpose": "main",
            }
        ],
        emphasis=[],
    )
    with pytest.raises(InvalidStateError, match="nonexistent"):
        EditPlanValidator().validate(invalid, source_duration=10, transcript_segments=SEGMENTS)


def test_clip_cannot_hide_an_intersecting_transcript_segment() -> None:
    segments = [
        {"start": 0, "end": 3, "text": "Первый"},
        {"start": 3, "end": 7, "text": "Средний"},
        {"start": 7, "end": 10, "text": "Последний"},
    ]
    invalid = plan(
        clips=[
            {
                "source_start": 0,
                "source_end": 10,
                "source_segment_ids": [0, 2],
                "purpose": "main",
            }
        ],
        emphasis=[],
    )
    with pytest.raises(InvalidStateError, match="every transcript segment"):
        EditPlanValidator().validate(invalid, source_duration=10, transcript_segments=segments)


def test_invented_emphasis_is_rejected() -> None:
    invalid = plan(emphasis=[{"start": 0, "end": 1, "text": "300% продаж"}])
    with pytest.raises(InvalidStateError, match="not present"):
        EditPlanValidator().validate(invalid, source_duration=10, transcript_segments=SEGMENTS)


def test_ai_clip_boundary_cannot_cut_through_speech() -> None:
    invalid = plan(
        clips=[
            {
                "source_start": 0.8,
                "source_end": 4.2,
                "source_segment_ids": [0],
                "purpose": "main",
            }
        ],
        emphasis=[],
    )
    with pytest.raises(InvalidStateError, match="spoken word"):
        EditPlanValidator(minimum_duration=2).validate(
            invalid,
            source_duration=10,
            transcript_segments=SEGMENTS,
            require_speech_boundaries=True,
        )
