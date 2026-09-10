"""Phase 6 capability smoke: real media pipeline plus deterministic fake Director.

The report explicitly separates the fake Director result from any real LLM result.
It is intentionally runnable offline; web asset search is not used by this smoke.
"""

import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.base import Base
from app.director.agent import DirectorAgent, FakeDirectorModel
from app.director.runtime import DirectorRunService, DirectorRuntime
from app.director.schemas import OutputProfile
from app.models import (
    ProductionProject,
    Project,
    SourceItem,
    TimelineRevision,
    User,
    VideoProject,
    VisualAsset,
)
from app.models.enums import AssetStatus, AssetType, SourceStatus, SourceType, UserRole
from app.quality.visual_critic import DeterministicVisualCritic
from app.schemas.production import ProductionProjectCreate, ProductionTimeline, ScriptVersionCreate
from app.services.errors import ProcessingError
from app.services.production_projects import ProductionProjectService
from app.services.production_rendering import probe_json
from app.services.production_scripts import ScriptVersionService
from app.services.stt import FasterWhisperProvider
from app.services.tts import EspeakTTSProvider
from app.services.voiceovers import VoiceoverService
from app.storage.local import LocalStorage

SCRIPT = (
    "Мобильное приложение не должно обращаться в 1С напрямую. "
    "Стабильный backend проверяет данные, защищает от повторов и изолирует клиент "
    "от внутренних изменений учётной системы."
)


async def run_command(*args: str) -> None:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    if process.returncode:
        raise RuntimeError(stderr.decode(errors="replace")[-2000:])


def make_image(path: Path, label: str) -> None:
    image = Image.new("RGB", (720, 1280), "#175CD3")
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((70, 140, 650, 1100), radius=40, fill="#F8FAFC")
    draw.text((180, 600), label, fill="#101828")
    image.save(path)


async def main() -> None:
    artifact_dir = Path(os.environ.get("DIRECTOR_ARTIFACT_DIR", "data/director-test-runs/latest"))
    try:
        with tempfile.TemporaryDirectory(prefix="director-e2e-") as raw_root:
            root = Path(raw_root)
            media_root = root / "media"
            fixtures = media_root / "fixtures"
            fixtures.mkdir(parents=True)
            render_temp = root / "render-temp"
            voice_path = fixtures / "voice.wav"
            tts_result = await EspeakTTSProvider(default_language="ru", rate=125).synthesize(
                SCRIPT, voice_path
            )
            settings_from_env = Settings()
            stt = await FasterWhisperProvider(
                settings_from_env.stt_model,
                settings_from_env.stt_device,
                settings_from_env.stt_compute_type,
            ).transcribe(voice_path, vocabulary=["REST API", "1С"], language="ru")

            screen = fixtures / "screen.png"
            long_video = fixtures / "long-scenes.mp4"
            make_image(screen, "APP UI")
            await run_command(
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc2=size=720x1280:rate=24:duration=8",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                str(long_video),
            )

            engine = create_async_engine(f"sqlite+aiosqlite:///{root / 'director.db'}")
            async with engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
            factory = async_sessionmaker(engine, expire_on_commit=False)
            async with factory() as session:
                project = Project(name="Director smoke", brand_context="clean technical dark")
                owner = User(telegram_id=1, role=UserRole.OWNER)
                session.add_all([project, owner])
                await session.flush()
                idea = SourceItem(
                    project_id=project.id,
                    user_id=owner.id,
                    type=SourceType.TEXT,
                    original_text="Почему приложение не должно ходить в 1С напрямую",
                    processing_status=SourceStatus.READY,
                )
                session.add(idea)
                await session.commit()
                production = await ProductionProjectService(session).create(
                    ProductionProjectCreate(
                        project_id=project.id,
                        user_id=owner.id,
                        initial_source_item_id=idea.id,
                        title=idea.original_text or "Director smoke",
                    )
                )
                script = await ScriptVersionService(session).create(
                    production.id, ScriptVersionCreate(content=SCRIPT)
                )
                await ScriptVersionService(session).approve(script.id)
                voice_source = SourceItem(
                    project_id=project.id,
                    user_id=owner.id,
                    type=SourceType.AUDIO,
                    local_file_path="fixtures/voice.wav",
                    processed_file_path="fixtures/voice.wav",
                    duration_seconds=tts_result.duration,
                    transcript=stt.text,
                    transcript_language=stt.language,
                    transcript_segments=[item.model_dump() for item in stt.segments],
                    processing_status=SourceStatus.READY,
                )
                session.add(voice_source)
                await session.commit()
                await VoiceoverService(session).create_from_processed_source(
                    production.id, voice_source.id
                )
                video_asset = VisualAsset(
                    project_id=project.id,
                    type=AssetType.VIDEO,
                    status=AssetStatus.READY,
                    original_path="fixtures/long-scenes.mp4",
                    filename=long_video.name,
                    mime_type="video/mp4",
                    file_size=long_video.stat().st_size,
                    duration=8,
                    title="backend technical footage",
                    description="backend technical footage",
                    tags=["backend", "technical"],
                    analysis={
                        "scene_segments": [
                            {"start": 0, "end": 2, "description": "opening"},
                            {"start": 2, "end": 5, "description": "relevant technical scene"},
                        ]
                    },
                )
                image_asset = VisualAsset(
                    project_id=project.id,
                    type=AssetType.SCREENSHOT,
                    status=AssetStatus.READY,
                    original_path="fixtures/screen.png",
                    filename=screen.name,
                    mime_type="image/png",
                    file_size=screen.stat().st_size,
                    width=720,
                    height=1280,
                    title="application screenshot",
                    description="application UI screenshot",
                    tags=["ui"],
                )
                session.add_all([video_asset, image_asset])
                await session.commit()
                settings = Settings(
                    media_root=str(media_root),
                    render_temp_root=str(render_temp),
                    preview_width=720,
                    preview_height=1280,
                    video_width=1080,
                    video_height=1920,
                    preview_preset="ultrafast",
                    video_preset="ultrafast",
                    video_encoder="libx264",
                    audio_normalization_enabled=False,
                    director_enabled=True,
                )
                run = await DirectorRunService(session, settings).start(
                    production.id,
                    "Собери технический short с релевантным B-roll и понятной графикой",
                )
                run = await DirectorAgent(
                    DirectorRuntime(session, production.id, settings), FakeDirectorModel(), settings
                ).run(run)
                if run.status != "completed":
                    raise RuntimeError(run.error or "Director fake run failed")
                refreshed = await session.get(ProductionProject, production.id)
                if refreshed is None or not refreshed.active_timeline_revision_id:
                    raise RuntimeError("Director did not create an active revision")
                revision = await session.get(
                    TimelineRevision, refreshed.active_timeline_revision_id
                )
                if revision is None:
                    raise RuntimeError("Director revision disappeared")
                timeline = ProductionTimeline.model_validate(revision.timeline_json)
                profile = OutputProfile.for_platform("youtube_shorts")
                quality = DeterministicVisualCritic(settings).evaluate(timeline, profile)
                video = await session.get(VideoProject, refreshed.active_video_project_id)
                if video is None or not video.final_path:
                    raise RuntimeError("Director did not produce final video")
                final_path = LocalStorage(str(media_root)).resolve(video.final_path)
                probe = await probe_json(final_path)
                streams = {item["codec_type"]: item for item in probe["streams"]}
                await asyncio.to_thread(artifact_dir.mkdir, parents=True, exist_ok=True)
                await asyncio.to_thread(shutil.copy2, final_path, artifact_dir / "final.mp4")
                if video.preview_path:
                    await asyncio.to_thread(
                        shutil.copy2,
                        LocalStorage(str(media_root)).resolve(video.preview_path),
                        artifact_dir / "preview-1.mp4",
                    )
                await asyncio.to_thread(
                    (artifact_dir / "timeline.json").write_text,
                    json.dumps(timeline.model_dump(mode="json"), ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                await asyncio.to_thread(
                    (artifact_dir / "quality-report.json").write_text,
                    json.dumps(quality, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                report = {
                    "status": "passed",
                    "deterministic_fake_director": "passed",
                    "real_openai_compatible_director": "not_tested",
                    "run_id": str(run.id),
                    "steps": run.step_count,
                    "llm_calls": run.llm_call_count,
                    "revisions": run.current_revision_id is not None,
                    "final": {
                        "duration": float(probe["format"]["duration"]),
                        "video": {
                            key: streams["video"].get(key)
                            for key in ("codec_name", "width", "height", "pix_fmt")
                        },
                        "audio": streams.get("audio", {}).get("codec_name"),
                    },
                    "quality": quality,
                    "artifacts": str(artifact_dir),
                }
                await asyncio.to_thread(
                    (artifact_dir / "director-report.json").write_text,
                    json.dumps(report, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
                print(json.dumps(report, ensure_ascii=False, indent=2))
            await engine.dispose()
    except (FileNotFoundError, OSError, ProcessingError, RuntimeError) as exc:
        report = {
            "status": "not_tested",
            "deterministic_fake_director": "not_tested",
            "real_openai_compatible_director": "not_tested",
            "reason": str(exc),
        }
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
