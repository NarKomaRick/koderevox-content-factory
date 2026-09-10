import uuid

from app.director.schemas import OutputProfile
from app.editing.layout import LayoutEngine
from app.editing.validation import TimelineValidator
from app.models.enums import TimelineTrack
from app.schemas.production import ProductionTimeline, TimelineItem


def test_output_profiles_keep_platform_geometry_in_application() -> None:
    profile = OutputProfile.for_platform("tiktok")

    assert (profile.width, profile.height, profile.aspect_ratio) == (1080, 1920, "9:16")
    assert profile.safe_zones.bottom == 420


def test_layout_engine_places_text_inside_safe_zone() -> None:
    profile = OutputProfile.for_platform("youtube_shorts")
    box = LayoutEngine().place("REST API", profile, anchor="top_center")

    assert box.x >= profile.safe_zones.left
    assert box.right <= profile.width - profile.safe_zones.right
    assert box.y >= profile.safe_zones.top


def test_text_validator_detects_collision_and_outside_canvas() -> None:
    profile = OutputProfile.for_platform("youtube_shorts")
    first_id, second_id = uuid.uuid4(), uuid.uuid4()
    timeline = ProductionTimeline(
        duration=10,
        voiceover_track_id=uuid.uuid4(),
        items=[
            TimelineItem(
                id=first_id,
                track=TimelineTrack.TEXT,
                start=1,
                end=4,
                text="First",
                metadata={
                    "text_layout": {
                        "x": 100,
                        "y": 200,
                        "width": 400,
                        "height": 100,
                        "font_size": 52,
                    }
                },
            ),
            TimelineItem(
                id=second_id,
                track=TimelineTrack.TEXT,
                start=2,
                end=5,
                text="Second",
                metadata={
                    "text_layout": {
                        "x": 200,
                        "y": 250,
                        "width": 400,
                        "height": 100,
                        "font_size": 52,
                    }
                },
            ),
        ],
    )

    report = TimelineValidator(LayoutEngine()).validate(timeline, profile)

    assert not report.ok
    assert any(issue.code == "TEXT_TEXT_COLLISION" for issue in report.issues)


def test_layout_engine_does_not_shrink_below_minimum() -> None:
    profile = OutputProfile.for_platform("youtube_shorts")
    box = LayoutEngine().place("A very long readable title " * 20, profile, font_size=40)

    assert box.font_size >= 28
