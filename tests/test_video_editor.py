import asyncio
import shutil

import pytest
from PIL import Image

from app.models.enums import SubtitlePreset
from app.schemas.video import EditPlan, ManualFraming
from app.services.framing import StaticFramingProvider
from app.services.pause import TimeRange
from app.services.subtitles import SubtitleCue, SubtitleService
from app.services.video_editor import FFmpegVideoEditor


def edit_plan() -> EditPlan:
    return EditPlan.model_validate(
        {
            "clips": [
                {
                    "source_start": 0,
                    "source_end": 2.5,
                    "source_segment_ids": [0],
                    "purpose": "hook",
                },
                {"source_start": 3, "source_end": 6, "source_segment_ids": [1], "purpose": "main"},
            ],
            "hook_text": "Технический разбор",
            "emphasis": [],
            "recommended_duration": 5.5,
            "reasoning_summary": "Два последовательных фрагмента",
            "framing": "center_crop",
            "pace": "medium",
        }
    )


def settings() -> dict[str, object]:
    return {
        "width": 1080,
        "height": 1920,
        "fps": 30,
        "crf": 24,
        "preset": "ultrafast",
        "audio_normalization": True,
        "noise_reduction": False,
        "hook_overlay": False,
    }


def test_ffmpeg_command_has_concat_vertical_audio_and_faststart(tmp_path) -> None:
    command = FFmpegVideoEditor().build_command(
        source=tmp_path / "source.mp4",
        destination=tmp_path / "out.mp4",
        clips=[TimeRange(0, 2.5), TimeRange(3, 6)],
        plan=edit_plan(),
        subtitle_file=tmp_path / "captions.ass",
        settings=settings(),
    )
    joined = " ".join(command)
    assert "concat=n=2:v=1:a=1" in joined
    assert "crop=1080:1920" in joined
    assert "loudnorm" in joined
    assert "+faststart" in command
    assert "yuv420p" in command


def test_static_framing_supports_blur_screen_fit_and_manual() -> None:
    provider = StaticFramingProvider()
    blurred = provider.filter_graph("in", "out", "fit_blur", width=1080, height=1920)
    screen = provider.filter_graph("in", "out", "screen_fit", width=1080, height=1920)
    manual = provider.filter_graph(
        "in",
        "out",
        "manual",
        width=1080,
        height=1920,
        manual=ManualFraming(x=0.25, y=0.5, zoom=1.5),
    )
    assert "boxblur=24" in blurred
    assert "boxblur=12" in screen
    assert "scale=1620:2880" in manual
    assert "crop=1080:1920:(iw-ow)*0.25" in manual


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is required")
async def test_real_vertical_render_burns_subtitles_and_extracts_frames(tmp_path) -> None:
    source = tmp_path / "source.mp4"
    process = await asyncio.create_subprocess_exec(
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "color=c=blue:s=640x360:r=30:d=6",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:duration=6",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-shortest",
        str(source),
    )
    assert await process.wait() == 0
    subtitles = SubtitleService().write_ass(
        tmp_path / "captions.ass",
        [SubtitleCue(0.2, 5.2, "СУБТИТРЫ РЕАЛЬНО В КАДРЕ")],
        preset=SubtitlePreset.TECH,
        width=1080,
        height=1920,
    )
    editor = FFmpegVideoEditor()
    result = await editor.render(
        source=source,
        destination=tmp_path / "vertical.mp4",
        clips=[TimeRange(0, 2.5), TimeRange(3, 6)],
        plan=edit_plan(),
        subtitle_file=subtitles,
        settings=settings(),
    )

    assert (result.width, result.height) == (1080, 1920)
    assert result.video_codec == "h264"
    assert result.audio_codec == "aac"
    assert 5.3 <= result.duration <= 5.7
    frames = await editor.extract_preview_frames(
        result.output_path, tmp_path / "frames", result.duration
    )
    assert len(frames) == 4
    with Image.open(frames[2]) as frame:
        assert frame.size == (1080, 1920)
        # The solid-blue source has near-white pixels only after ASS text is burned in.
        red_range, green_range, _blue_range = frame.convert("RGB").getextrema()
    assert red_range[1] > 220
    assert green_range[1] > 220
