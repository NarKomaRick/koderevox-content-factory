import asyncio
import shutil

import pytest
from PIL import Image

from app.core.config import Settings
from app.models import Project, VideoProject
from app.models.enums import SubtitlePreset, ThumbnailStatus, VideoProjectStatus
from app.schemas.thumbnails import ThumbnailConcept
from app.schemas.video import EditPlan
from app.schemas.visual import VisualInsertion
from app.services.graphics import CodeCardRenderer, ThumbnailRenderer
from app.services.pause import TimeRange
from app.services.subtitles import SubtitleCue, SubtitleService
from app.services.thumbnails import ThumbnailService
from app.services.video_editor import FFmpegVideoEditor, VisualRenderAsset
from app.storage.local import LocalStorage


def plan() -> EditPlan:
    return EditPlan.model_validate(
        {
            "clips": [
                {
                    "source_start": 0,
                    "source_end": 16,
                    "source_segment_ids": [0],
                    "purpose": "main",
                }
            ],
            "hook_text": "REST API",
            "recommended_duration": 16,
            "reasoning_summary": "Synthetic Phase 4 smoke",
            "framing": "center_crop",
            "pace": "medium",
        }
    )


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg is required")
async def test_real_phase4_visual_pipeline_and_debug_frames(tmp_path) -> None:
    source = tmp_path / "talking-head.mp4"
    screen = tmp_path / "screen.mp4"
    for output, color, duration in ((source, "blue", 16), (screen, "yellow", 3)):
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            f"color=c={color}:s=540x960:r=24:d={duration}",
            "-f",
            "lavfi",
            "-i",
            f"sine=frequency=440:sample_rate=48000:duration={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-shortest",
            str(output),
        )
        assert await process.wait() == 0
    screenshot = tmp_path / "screenshot.png"
    pip = tmp_path / "pip.png"
    Image.new("RGB", (900, 1600), "red").save(screenshot)
    Image.new("RGB", (1000, 700), "green").save(pip)
    code = await CodeCardRenderer().render(
        "async def request():\n    return await api.get('/bestway')",
        tmp_path / "code.png",
    )
    subtitles = SubtitleService().write_ass(
        tmp_path / "captions.ass",
        [SubtitleCue(0.2, 15.8, "ПРОВЕРЯЕМ ВИЗУАЛЬНЫЙ PIPELINE")],
        preset=SubtitlePreset.TECH,
        width=1080,
        height=1920,
    )
    visuals = [
        VisualRenderAsset(
            VisualInsertion(
                start=4,
                end=7,
                asset_id=__import__("uuid").uuid4(),
                layout="fullscreen",
            ),
            screenshot,
        ),
        VisualRenderAsset(
            VisualInsertion(
                start=7,
                end=10,
                asset_id=__import__("uuid").uuid4(),
                layout="picture_in_picture",
            ),
            pip,
        ),
        VisualRenderAsset(
            VisualInsertion(
                start=10,
                end=13,
                asset_id=__import__("uuid").uuid4(),
                layout="fullscreen",
            ),
            screen,
            True,
        ),
        VisualRenderAsset(
            VisualInsertion(
                start=13,
                end=16,
                asset_id=__import__("uuid").uuid4(),
                layout="code_card",
            ),
            code,
        ),
    ]
    editor = FFmpegVideoEditor()
    result = await editor.render(
        source=source,
        destination=tmp_path / "phase4.mp4",
        clips=[TimeRange(0, 16)],
        plan=plan(),
        subtitle_file=subtitles,
        settings={
            "width": 1080,
            "height": 1920,
            "fps": 24,
            "crf": 27,
            "preset": "ultrafast",
            "audio_normalization": True,
            "noise_reduction": False,
            "hook_overlay": False,
            "safe_margin_top": 140,
        },
        visuals=visuals,
    )
    assert (result.width, result.height) == (1080, 1920)
    assert result.video_codec == "h264" and result.audio_codec == "aac"
    assert 15.7 <= result.duration <= 16.3
    frames = await editor.extract_debug_frames(
        result.output_path, tmp_path / "debug", [2, 5.5, 8.5, 11.5, 14.5]
    )
    assert len(frames) == 5 and all(frame.stat().st_size > 1000 for frame in frames)
    center_colors = []
    for frame in frames:
        with Image.open(frame) as image:
            assert image.size == (1080, 1920)
            center_colors.append(image.convert("RGB").getpixel((540, 800)))
    assert center_colors[0][2] > center_colors[0][0]
    assert center_colors[1][0] > center_colors[1][2]
    assert center_colors[3][0] > 150 and center_colors[3][1] > 150
    assert center_colors[4] != center_colors[0]


async def test_real_thumbnail_and_code_card_dimensions(tmp_path) -> None:
    subject = tmp_path / "subject.png"
    Image.new("RGB", (720, 1280), "#285078").save(subject)
    output = tmp_path / "thumbnail.jpg"
    await ThumbnailRenderer().render(
        ThumbnailConcept(headline="ДВА ЗАПРОСА", emphasis_words=["ДВА"]),
        output,
        subject_path=subject,
        width=1280,
        height=720,
        font_path="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    )
    with Image.open(output) as image:
        assert image.size == (1280, 720)
        assert image.format == "JPEG"
    code = await CodeCardRenderer().render("def answer():\n    return 42", tmp_path / "code.png")
    with Image.open(code) as image:
        assert image.size == (900, 1100)


async def test_thumbnail_service_creates_three_concepts_and_selects_one(session, tmp_path) -> None:
    from sqlalchemy import select

    project = (await session.scalars(select(Project))).one()
    video = VideoProject(
        project_id=project.id,
        source_item_id=__import__("uuid").uuid4(),
        status=VideoProjectStatus.RENDERED,
        edit_plan=plan().model_dump(mode="json"),
    )
    session.add(video)
    await session.commit()
    settings = Settings(
        media_root=str(tmp_path / "media"),
        render_temp_root=str(tmp_path / "render"),
    )
    service = ThumbnailService(session, LocalStorage(settings.media_root), settings)
    thumbnails = await service.generate(video.id)
    assert len(thumbnails) == 3
    assert all(item.status == ThumbnailStatus.RENDERED for item in thumbnails)
    for item in thumbnails:
        assert item.output_path
        with Image.open(service.storage.resolve(item.output_path)) as image:
            assert image.size == (1280, 720)
    selected = await service.select(thumbnails[1].id)
    assert selected.status == ThumbnailStatus.SELECTED
    assert video.selected_thumbnail_id == selected.id


def test_phase4_telegram_buttons_are_present() -> None:
    from app.bot.keyboards import main_menu, thumbnail_keyboard, visual_suggestions_keyboard

    menu = main_menu()
    labels = [button.text for row in menu.keyboard for button in row]
    assert "📎 Добавить материалы" in labels
    assert "🗂 Материалы" in labels
    visual = visual_suggestions_keyboard("project")
    callbacks = [button.callback_data for row in visual.inline_keyboard for button in row]
    assert "visual_apply:project" in callbacks
    thumbnail = thumbnail_keyboard([{"id": "a"}, {"id": "b"}, {"id": "c"}], "project")
    assert len(thumbnail.inline_keyboard[0]) == 3
