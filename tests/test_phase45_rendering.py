import asyncio
from pathlib import Path

import pytest
from PIL import Image, ImageDraw
from sqlalchemy import select

from app.core.config import Settings
from app.models import (
    ProductionProject,
    Project,
    SourceItem,
    TimelineRevision,
    User,
    VisualAsset,
    VoiceoverTrack,
)
from app.models.enums import (
    AssetStatus,
    AssetType,
    ProductionStatus,
    SourceStatus,
    SourceType,
    TimelineTrack,
    UserRole,
    VoiceoverStatus,
)
from app.schemas.production import ProductionTimeline, TimelineItem
from app.services.production_rendering import ProductionRenderService, probe_json
from app.storage.local import LocalStorage


async def command(*args: str) -> None:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    assert process.returncode == 0, stderr.decode(errors="replace")


@pytest.mark.asyncio
async def test_voiceover_driven_preview_and_final_real_ffmpeg(session, tmp_path: Path) -> None:
    media_root = tmp_path / "media"
    render_temp = tmp_path / "temp"
    originals = media_root / "fixtures"
    originals.mkdir(parents=True)
    audio = originals / "voice.wav"
    await command(
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=48000:duration=3",
        "-c:a",
        "pcm_s16le",
        str(audio),
    )
    screenshot = originals / "screen.png"
    image = Image.new("RGB", (720, 1280), "#175CD3")
    draw = ImageDraw.Draw(image)
    draw.rectangle((80, 100, 640, 1100), fill="#FFFFFF")
    draw.text((180, 550), "REAL UI", fill="#101828")
    image.save(screenshot)

    project = (await session.scalars(select(Project))).first()
    assert project
    project.vocabulary = ["REST API"]
    user = User(telegram_id=55, role=UserRole.OWNER)
    session.add(user)
    await session.flush()
    source = SourceItem(
        project_id=project.id,
        user_id=user.id,
        type=SourceType.AUDIO,
        local_file_path="fixtures/voice.wav",
        processed_file_path="fixtures/voice.wav",
        duration_seconds=3,
        transcript="это реальная речь для проверки",
        transcript_language="ru",
        transcript_segments=[
            {
                "start": 0,
                "end": 3,
                "text": "это реальная речь для проверки",
                "words": [
                    {"word": word, "start": i * 0.5, "end": (i + 1) * 0.5}
                    for i, word in enumerate("это реальная речь для проверки".split())
                ],
            }
        ],
        processing_status=SourceStatus.READY,
    )
    asset = VisualAsset(
        project_id=project.id,
        type=AssetType.SCREENSHOT,
        status=AssetStatus.READY,
        original_path="fixtures/screen.png",
        filename="screen.png",
        mime_type="image/png",
        file_size=screenshot.stat().st_size,
        width=720,
        height=1280,
        title="Real UI",
        tags=["ui"],
    )
    session.add_all([source, asset])
    await session.flush()
    production = ProductionProject(
        project_id=project.id,
        user_id=user.id,
        title="Smoke",
        working_title="Smoke",
        status=ProductionStatus.ROUGH_CUT,
    )
    session.add(production)
    await session.flush()
    voice = VoiceoverTrack(
        production_project_id=production.id,
        source_item_id=source.id,
        original_path=source.local_file_path,
        processed_path=source.processed_file_path,
        duration=3,
        language="ru",
        transcript=source.transcript,
        segments=source.transcript_segments,
        words=source.transcript_segments[0]["words"],
        status=VoiceoverStatus.READY,
    )
    session.add(voice)
    await session.flush()
    timeline = ProductionTimeline(
        duration=3,
        voiceover_track_id=voice.id,
        items=[
            TimelineItem(track=TimelineTrack.AUDIO_MASTER, start=0, end=3),
            TimelineItem(track=TimelineTrack.SUBTITLES, start=0, end=3),
            TimelineItem(
                track=TimelineTrack.BROLL,
                start=0,
                end=1.5,
                asset_id=asset.id,
                metadata={"asset_type": "screenshot", "muted": True},
            ),
            TimelineItem(
                track=TimelineTrack.TEXT,
                start=1.5,
                end=3,
                text="REST API",
                layout="code_card",
            ),
        ],
    )
    revision = TimelineRevision(
        production_project_id=production.id,
        revision_number=1,
        timeline_json=timeline.model_dump(mode="json"),
    )
    session.add(revision)
    await session.flush()
    production.primary_voiceover_id = voice.id
    production.active_timeline_revision_id = revision.id
    await session.commit()

    settings = Settings(
        media_root=str(media_root),
        render_temp_root=str(render_temp),
        preview_width=360,
        preview_height=640,
        video_width=540,
        video_height=960,
        preview_preset="ultrafast",
        video_preset="ultrafast",
        audio_normalization_enabled=False,
    )
    service = ProductionRenderService(session, LocalStorage(str(media_root)), settings)
    preview = await service.render(production.id, profile_name="preview")
    assert preview.preview_path
    preview_probe = await probe_json(LocalStorage(str(media_root)).resolve(preview.preview_path))
    preview_video = next(s for s in preview_probe["streams"] if s["codec_type"] == "video")
    assert (preview_video["width"], preview_video["height"]) == (360, 640)
    final = await service.render(production.id, profile_name="final")
    assert final.final_path and final.status.value == "approved"
    final_path = LocalStorage(str(media_root)).resolve(final.final_path)
    probe = await probe_json(final_path)
    streams = {stream["codec_type"]: stream for stream in probe["streams"]}
    assert (streams["video"]["width"], streams["video"]["height"]) == (540, 960)
    assert streams["video"]["codec_name"] == "h264"
    assert streams["video"]["pix_fmt"] == "yuv420p"
    assert streams["audio"]["codec_name"] == "aac"
    assert abs(float(probe["format"]["duration"]) - 3) < 0.2
    assert not list(render_temp.glob("production-*"))

    frame = tmp_path / "subtitle-frame.png"
    await command(
        "ffmpeg",
        "-y",
        "-v",
        "error",
        "-ss",
        "0.8",
        "-i",
        str(final_path),
        "-frames:v",
        "1",
        str(frame),
    )
    with Image.open(frame) as rendered:
        colors = rendered.convert("RGB").getcolors(maxcolors=rendered.width * rendered.height)
        assert colors and len(colors) > 20  # UI plus burned ASS glyphs are visibly present.
