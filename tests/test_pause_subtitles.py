from app.models.enums import SubtitlePreset
from app.schemas.video import EditClip
from app.services.pause import FFmpegPauseDetector, TimeRange, clips_without_long_pauses
from app.services.subtitles import SubtitleService


def test_pause_detector_parses_ffmpeg_output() -> None:
    stderr = """
[silencedetect @ x] silence_start: 1.25
[silencedetect @ x] silence_end: 2.10 | silence_duration: 0.85
[silencedetect @ x] silence_start: 5.0
[silencedetect @ x] silence_end: 6.2 | silence_duration: 1.2
"""
    assert FFmpegPauseDetector.parse(stderr) == [TimeRange(1.25, 2.1), TimeRange(5, 6.2)]


def test_long_pause_removed_with_padding_and_short_pause_preserved() -> None:
    clips = [EditClip(source_start=0, source_end=8, source_segment_ids=[0], purpose="main")]
    ranges = clips_without_long_pauses(
        clips,
        [TimeRange(1, 1.4), TimeRange(3, 4)],
        keep_padding=0.12,
    )
    assert ranges == [TimeRange(0, 3.12), TimeRange(3.88, 8)]


def test_subtitle_chunks_keep_timing_and_terminology(tmp_path) -> None:
    segments = [
        {
            "start": 0,
            "end": 4,
            "text": "Когда рест апи отправил запрос снова",
            "words": [
                {"word": "Когда", "start": 0, "end": 0.5},
                {"word": "REST API", "start": 0.5, "end": 1.4},
                {"word": "отправил", "start": 1.4, "end": 2.1},
                {"word": "запрос", "start": 2.1, "end": 2.8},
                {"word": "снова", "start": 2.8, "end": 4},
            ],
        }
    ]
    service = SubtitleService()
    cues = service.create_cues(
        segments,
        [TimeRange(0, 4)],
        preset=SubtitlePreset.TECH,
        vocabulary=["REST API"],
        overrides={"отправил": "ОТПРАВИЛ"},
    )

    assert cues[0].start == 0
    assert cues[-1].end == 4
    assert "REST API" in " ".join(cue.text for cue in cues)
    assert "ОТПРАВИЛ" in " ".join(cue.text for cue in cues)
    ass = service.write_ass(
        tmp_path / "captions.ass",
        cues + [type(cues[0])(4, 5, "скобки {важно} \\ путь")],
        preset=SubtitlePreset.TECH,
        width=1080,
        height=1920,
    )
    content = ass.read_text(encoding="utf-8")
    assert "Dialogue:" in content
    assert r"\{важно\}" in content
    assert r"\\ путь" in content


def test_dynamic_subtitles_use_timed_active_word_highlighting(tmp_path) -> None:
    service = SubtitleService()
    cues = service.create_cues(
        [
            {
                "start": 0,
                "end": 1,
                "text": "два запроса",
                "words": [
                    {"word": "два", "start": 0, "end": 0.4},
                    {"word": "запроса", "start": 0.4, "end": 1},
                ],
            }
        ],
        [TimeRange(0, 1)],
        preset=SubtitlePreset.DYNAMIC,
    )
    path = service.write_ass(
        tmp_path / "dynamic.ass",
        cues,
        preset=SubtitlePreset.DYNAMIC,
        width=1080,
        height=1920,
    )
    content = path.read_text(encoding="utf-8")
    assert r"{\kf40}два" in content
    assert r"{\kf60}запроса" in content
