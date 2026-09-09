"""Real local Phase 4.5 smoke: TTS -> Whisper -> revisions -> FFmpeg renders."""

import asyncio
import hashlib
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.base import Base
from app.models import Project, SourceItem, User, VisualAsset
from app.models.enums import (
    AssetStatus,
    AssetType,
    ProductionMaterialRole,
    ScriptSource,
    SourceStatus,
    SourceType,
    UserRole,
)
from app.schemas.production import MaterialAttach, ProductionProjectCreate, ScriptVersionCreate
from app.services.media import FFmpegMediaProcessor
from app.services.production_projects import ProductionMaterialService, ProductionProjectService
from app.services.production_rendering import ProductionRenderService, probe_json
from app.services.production_scripts import ScriptVersionService
from app.services.production_timeline import AutoAssemblyService
from app.services.stt import FasterWhisperProvider
from app.services.tts import EspeakTTSProvider
from app.services.voiceovers import VoiceoverService
from app.storage.local import LocalStorage

SCRIPT = """Прямой доступ мобильного приложения к 1С кажется простым только в начале.
Когда 1С отвечает медленно, пользователь видит зависший интерфейс и повторяет действие.
Так появляется двойной запрос, а в базе возникают две одинаковые записи.
Backend со стабильным REST API проверяет данные, ограничивает повторы и кэширует ответы.
Экран приложения остаётся быстрым, даже если внутренняя система временно недоступна.
Без backend всё окончательно сломалось бы после очередного обновления."""


async def run_command(*args: str) -> None:
    process = await asyncio.create_subprocess_exec(
        *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    _, stderr = await process.communicate()
    if process.returncode:
        raise RuntimeError(stderr.decode(errors="replace"))


def image(path: Path, color: str, label: str) -> None:
    canvas = Image.new("RGB", (720, 1280), color)
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((70, 140, 650, 1100), 40, fill="#F8FAFC")
    draw.text((170, 600), label, fill="#101828")
    canvas.save(path)


async def main() -> None:
    with tempfile.TemporaryDirectory(prefix="snowball-e2e-") as raw_root:
        root = Path(raw_root)
        media_root = root / "media"
        fixtures = media_root / "fixtures"
        fixtures.mkdir(parents=True)
        render_temp = root / "render-temp"
        original = fixtures / "voice-original.wav"
        processed = fixtures / "voice-processed.wav"
        tts = EspeakTTSProvider(default_language="ru", rate=125)
        tts_result = await tts.synthesize(SCRIPT, original)
        await FFmpegMediaProcessor().normalize_audio(original, processed)
        settings_from_env = Settings()
        stt_started = time.perf_counter()
        stt = await FasterWhisperProvider(
            settings_from_env.stt_model,
            settings_from_env.stt_device,
            settings_from_env.stt_compute_type,
        ).transcribe(
            processed, vocabulary=["REST API", "1С"], language="ru"
        )
        stt_elapsed_seconds = time.perf_counter() - stt_started
        duration = float(stt.duration or 0)
        if abs(duration - tts_result.duration) > 1.0:
            raise RuntimeError(f"TTS/STT duration mismatch: {tts_result.duration} vs {duration}")
        if not 25 <= duration <= 50:
            raise RuntimeError(f"Unexpected smoke voiceover duration: {duration}")

        screen = fixtures / "screen.png"
        meme = fixtures / "meme.png"
        code = fixtures / "api.py"
        recording = fixtures / "screen-recording.mp4"
        footage = fixtures / "footage.mp4"
        later = fixtures / "later-footage.mp4"
        image(screen, "#175CD3", "APP UI")
        image(meme, "#D92D20", "BROKEN DATABASE MEME")
        code.write_text(
            "async def create_order(payload):\n"
            "    key = payload.idempotency_key\n"
            "    return await one_c_adapter.send(payload, key)\n",
            encoding="utf-8",
        )
        for path, source in (
            (recording, "testsrc2=size=720x1280:rate=24:duration=7"),
            (footage, "smptebars=size=720x1280:rate=24:duration=7"),
            (later, "mandelbrot=size=720x1280:rate=24"),
        ):
            await run_command(
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-f",
                "lavfi",
                "-i",
                source,
                "-t",
                "7",
                "-c:v",
                "libx264",
                "-preset",
                "ultrafast",
                "-pix_fmt",
                "yuv420p",
                str(path),
            )

        engine = create_async_engine(f"sqlite+aiosqlite:///{root / 'smoke.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            brand = Project(
                name="Koderevox E2E",
                brand_context="technical clean dark minimal",
                target_audience="technical audience",
                vocabulary=["REST API", "1С"],
            )
            owner = User(telegram_id=1, role=UserRole.OWNER)
            session.add_all([brand, owner])
            await session.flush()
            idea = SourceItem(
                project_id=brand.id,
                user_id=owner.id,
                type=SourceType.TEXT,
                original_text="Почему приложение не должно напрямую ходить в 1С",
                processing_status=SourceStatus.READY,
            )
            session.add(idea)
            await session.commit()
            production = await ProductionProjectService(session).create(
                ProductionProjectCreate(
                    project_id=brand.id,
                    user_id=owner.id,
                    initial_source_item_id=idea.id,
                    title=idea.original_text or "E2E",
                )
            )
            scripts = ScriptVersionService(session)
            v1 = await scripts.create(
                production.id,
                ScriptVersionCreate(content=SCRIPT.replace("Backend", "Сервер")),
            )
            v2 = await scripts.create(
                production.id,
                ScriptVersionCreate(
                    content=SCRIPT,
                    source=ScriptSource.USER,
                    user_instruction="Верни технический термин Backend",
                ),
            )
            await scripts.approve(v2.id)
            voice_source = SourceItem(
                project_id=brand.id,
                user_id=owner.id,
                type=SourceType.AUDIO,
                local_file_path="fixtures/voice-original.wav",
                processed_file_path="fixtures/voice-processed.wav",
                duration_seconds=duration,
                transcript=stt.text,
                transcript_language=stt.language,
                transcript_segments=[item.model_dump() for item in stt.segments],
                processing_status=SourceStatus.READY,
            )
            session.add(voice_source)
            await session.commit()
            voice = await VoiceoverService(session).create_from_processed_source(
                production.id, voice_source.id
            )

            def asset(path: Path, kind: AssetType, title: str, tags: list[str]) -> VisualAsset:
                return VisualAsset(
                    project_id=brand.id,
                    type=kind,
                    status=AssetStatus.READY,
                    original_path=f"fixtures/{path.name}",
                    filename=path.name,
                    mime_type="video/mp4"
                    if kind in {AssetType.VIDEO, AssetType.SCREEN_RECORDING}
                    else "image/png",
                    file_size=path.stat().st_size,
                    duration=7 if kind in {AssetType.VIDEO, AssetType.SCREEN_RECORDING} else None,
                    title=title,
                    description=title,
                    tags=tags,
                    extracted_text=code.read_text() if kind == AssetType.CODE else None,
                )

            assets = [
                asset(screen, AssetType.SCREENSHOT, "мобильное приложение интерфейс", ["ui"]),
                asset(
                    recording,
                    AssetType.SCREEN_RECORDING,
                    "пользователь повторяет действие",
                    ["screen"],
                ),
                asset(footage, AssetType.VIDEO, "двойной запрос две записи", ["footage"]),
                asset(code, AssetType.CODE, "Backend REST API idempotency", ["code"]),
            ]
            session.add_all(assets)
            await session.commit()
            materials = ProductionMaterialService(session)
            roles = [
                ProductionMaterialRole.SCREENSHOT,
                ProductionMaterialRole.SCREEN_RECORDING,
                ProductionMaterialRole.FOOTAGE,
                ProductionMaterialRole.CODE,
            ]
            for item, role in zip(assets, roles, strict=True):
                await materials.attach(
                    production.id, MaterialAttach(asset_id=item.id, roles=[role])
                )

            settings = Settings(
                media_root=str(media_root),
                render_temp_root=str(render_temp),
                preview_width=720,
                preview_height=1280,
                video_width=1080,
                video_height=1920,
                preview_preset="ultrafast",
                video_preset="ultrafast",
                audio_normalization_enabled=False,
            )
            assembly = AutoAssemblyService(session, settings)
            revision1 = await assembly.assemble(production.id)
            renderer = ProductionRenderService(session, LocalStorage(str(media_root)), settings)
            preview1 = await renderer.render(production.id, profile_name="preview")
            preview1_path = preview1.preview_path

            meme_asset = asset(meme, AssetType.IMAGE, "всё окончательно сломалось", ["meme"])
            session.add(meme_asset)
            await session.commit()
            meme_material = await materials.attach(
                production.id,
                MaterialAttach(asset_id=meme_asset.id, roles=[ProductionMaterialRole.MEME]),
            )
            placement, revision2 = await assembly.insert_locked(
                production.id,
                meme_material.id,
                "Поставь мем где говорю, что всё окончательно сломалось",
                candidate_index=0,
            )
            if revision2 is None:
                raise RuntimeError(f"Semantic meme placement failed: {placement.status}")
            preview2 = await renderer.render(production.id, profile_name="preview")
            preview2_path = preview2.preview_path

            later_asset = asset(later, AssetType.VIDEO, "экран приложения быстрый", ["footage"])
            session.add(later_asset)
            await session.commit()
            later_material = await materials.attach(
                production.id,
                MaterialAttach(asset_id=later_asset.id, roles=[ProductionMaterialRole.FOOTAGE]),
            )
            _, revision3 = await assembly.insert_locked(
                production.id,
                later_material.id,
                "Используй это в моменте про экран приложения",
                candidate_index=0,
            )
            if revision3 is None:
                raise RuntimeError("Incremental footage insertion failed")
            revision4 = await assembly.local_replan(
                production.id, "Первые 15 секунд сделай быстрее"
            )
            final = await renderer.render(production.id, profile_name="final")
            final_path = LocalStorage(str(media_root)).resolve(final.final_path or "")
            probe = await probe_json(final_path)
            streams = {item["codec_type"]: item for item in probe["streams"]}
            debug_hashes: list[str] = []
            for index, section in enumerate(voice.alignment.get("sections", [])[:8]):
                frame = root / f"debug-{index}.png"
                await run_command(
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-ss",
                    str(section["start"]),
                    "-i",
                    str(final_path),
                    "-frames:v",
                    "1",
                    str(frame),
                )
                debug_hashes.append(hashlib.sha256(frame.read_bytes()).hexdigest()[:12])
            report = {
                "script_versions": [v1.version_number, v2.version_number],
                "voiceover_duration": duration,
                "stt_language": stt.language,
                "stt_words": sum(len(item.words) for item in stt.segments),
                "stt": {
                    "model": settings_from_env.stt_model,
                    "device": settings_from_env.stt_device,
                    "compute_type": settings_from_env.stt_compute_type,
                    "elapsed_seconds": round(stt_elapsed_seconds, 3),
                },
                "alignment_score": voice.alignment_score,
                "revisions": [
                    revision1.revision_number,
                    revision2.revision_number,
                    revision3.revision_number,
                    revision4.revision_number,
                ],
                "semantic_placement": placement.status,
                "preview1": preview1_path,
                "preview2": preview2_path,
                "final_duration": float(probe["format"]["duration"]),
                "final_video": {
                    key: streams["video"].get(key)
                    for key in ("codec_name", "width", "height", "pix_fmt")
                },
                "final_audio": streams["audio"].get("codec_name"),
                "debug_frame_hashes": debug_hashes,
                "temp_cleaned": not list(render_temp.glob("production-*")),
            }
            artifact_dir = Path(os.environ.get("CAPABILITY_ARTIFACT_DIR", "data/test-runs/latest"))
            artifact_dir.mkdir(parents=True, exist_ok=True)  # noqa: ASYNC240
            shutil.copy2(final_path, artifact_dir / "final.mp4")
            shutil.copy2(
                LocalStorage(str(media_root)).resolve(preview1_path), artifact_dir / "preview-1.mp4"
            )
            shutil.copy2(
                LocalStorage(str(media_root)).resolve(preview2_path), artifact_dir / "preview-2.mp4"
            )
            for index in range(len(debug_hashes)):
                source_frame = root / f"debug-{index}.png"
                if source_frame.exists():
                    shutil.copy2(source_frame, artifact_dir / f"debug-{index}.png")
            report["artifact_dir"] = str(artifact_dir)
            report["tts"] = {
                "provider": tts_result.provider,
                "language": tts_result.language,
                "voice": tts_result.voice,
                "duration": tts_result.duration,
            }
            (artifact_dir / "video_capability_report.json").write_text(
                json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            print(json.dumps(report, ensure_ascii=False, indent=2))
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
