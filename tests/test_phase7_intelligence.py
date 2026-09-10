import uuid

import pytest

from app.audio_intelligence.analyzer import AudioIntelligenceAnalyzer
from app.core.config import Settings
from app.director.schemas import OutputProfile
from app.director.story import DeterministicStoryAnalyst
from app.knowledge.retrieval import KnowledgeRetriever
from app.models.enums import TimelineTrack
from app.quality.critic_roles import ReviewAggregator
from app.schemas.production import ProductionTimeline, TimelineItem


@pytest.mark.asyncio
async def test_story_analysis_uses_semantic_ranges_and_voiceover_timestamps() -> None:
    analysis = await DeterministicStoryAnalyst().analyze(
        {
            "script": {"content": "first. second."},
            "voiceover": {
                "duration": 12,
                "segments": [
                    {"start": 0, "end": 2.7, "text": "The risk appears."},
                    {
                        "start": 3.4,
                        "end": 11.5,
                        "text": "The safer architecture explains the cause.",
                    },
                ],
            },
            "target": {"format": "short_video"},
            "brand": {"audience": "engineers", "context": "technical"},
        },
        "Make the story clear",
    )

    assert [(beat.start, beat.end) for beat in analysis.beats] == [(0, 2.7), (3.4, 11.5)]
    assert analysis.beats[0].purpose == "hook"
    assert analysis.beats[1].purpose == "resolution"


def test_audio_intelligence_reports_pause_rate_and_emphasis() -> None:
    result = AudioIntelligenceAnalyzer().from_metadata(
        10,
        [
            {"start": 0, "end": 3, "text": "one two three"},
            {"start": 4.4, "end": 9, "text": "slow explanation"},
        ],
        [
            {"start": 0, "end": 0.2, "word": "one"},
            {"start": 0.25, "end": 0.45, "word": "two"},
            {"start": 0.5, "end": 0.7, "word": "three!"},
        ],
    )

    assert any(item.kind == "long" for item in result.pauses)
    assert result.windows[0].words_per_second > 0
    assert result.emphasis


def test_knowledge_retrieval_is_bounded_and_task_specific() -> None:
    items = KnowledgeRetriever().search("hooks retention shorts", limit=3)

    assert 0 < len(items) <= 3
    assert all(len(item.text) <= 1600 for item in items)


def test_review_aggregator_keeps_hard_validation_separate() -> None:
    timeline = ProductionTimeline(
        duration=10,
        voiceover_track_id=uuid.uuid4(),
        items=[
            TimelineItem(
                track=TimelineTrack.BROLL,
                start=0,
                end=2,
                metadata={},
            )
        ],
    )
    review = ReviewAggregator(settings=Settings(video_font_path="")).evaluate(
        timeline, OutputProfile.for_platform("youtube_shorts")
    )

    assert review.hard_failures
    assert any(problem.kind == "MISSING_REFERENCED_ASSET" for problem in review.hard_failures)
    assert {report.role for report in review.reports} == {
        "visual",
        "story",
        "continuity",
        "pacing",
        "technical",
    }
