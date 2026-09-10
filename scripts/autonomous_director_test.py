"""Phase 7 capability test with explicit fake and real-model modes."""

import argparse
import asyncio
import json
import os
import shutil
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.factory import create_ai_provider
from app.core.config import Settings
from app.db.base import Base
from app.director.autonomous import AutonomousDirector
from app.director.runtime import DirectorRunService
from app.models import (
    DirectorAction,
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
    ScriptSource,
    SourceStatus,
    SourceType,
    UserRole,
    VoiceoverStatus,
)
from app.schemas.production import ProductionProjectCreate, ScriptVersionCreate
from app.services.production_projects import ProductionProjectService
from app.services.production_scripts import ScriptVersionService


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--fake", action="store_true", help="Run deterministic offline orchestration"
    )
    parser.add_argument(
        "--real", action="store_true", help="Use configured OpenAI-compatible Director"
    )
    parser.add_argument(
        "--report-dir",
        default=os.environ.get("DIRECTOR_ARTIFACT_DIR", "data/director-test-runs/phase7"),
    )
    return parser.parse_args()


async def main() -> None:
    args = arguments()
    fake = args.fake or not args.real
    report_dir = Path(args.report_dir)
    missing = [name for name in ("ffmpeg", "ffprobe", "espeak-ng") if shutil.which(name) is None]
    if not fake and missing:
        report = {
            "status": "not_tested",
            "fake_director": "not_tested",
            "real_director": "not_tested",
            "real_ffmpeg": "not_tested"
            if any(name in missing for name in ("ffmpeg", "ffprobe"))
            else "available",
            "real_tts": "not_tested" if "espeak-ng" in missing else "available",
            "real_vision": "not_tested",
            "web_asset_search": "not_tested",
            "reason": f"Missing required local executables: {', '.join(missing)}",
        }
        await asyncio.to_thread(report_dir.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(
            (report_dir / "autonomous-director-report.json").write_text,
            json.dumps(report, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    with tempfile.TemporaryDirectory(prefix="autonomous-director-") as raw_root:
        root = Path(raw_root)
        engine = create_async_engine(f"sqlite+aiosqlite:///{root / 'director.db'}")
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        async with factory() as session:
            owner = User(telegram_id=998877, role=UserRole.OWNER)
            project = Project(name="Phase 7 smoke", target_audience="technical viewers")
            session.add_all([owner, project])
            await session.flush()
            source = SourceItem(
                project_id=project.id,
                user_id=owner.id,
                type=SourceType.TEXT,
                original_text="Почему секрет нельзя хранить внутри мобильного клиента",
                processing_status=SourceStatus.READY,
            )
            session.add(source)
            await session.commit()
            production = await ProductionProjectService(session).create(
                ProductionProjectCreate(
                    project_id=project.id,
                    user_id=owner.id,
                    initial_source_item_id=source.id,
                    title="API key security",
                )
            )
            script = await ScriptVersionService(session).create(
                production.id,
                ScriptVersionCreate(
                    content=(
                        "Ключ внутри приложения доступен пользователю. Backend хранит секрет "
                        "и даёт клиенту безопасный контракт."
                    ),
                    source=ScriptSource.USER,
                ),
            )
            await ScriptVersionService(session).approve(script.id)
            voice_source = SourceItem(
                project_id=project.id,
                user_id=owner.id,
                type=SourceType.AUDIO,
                local_file_path="fixtures/voice.wav",
                processed_file_path="fixtures/voice.wav",
                duration_seconds=8,
                transcript=(
                    "Ключ внутри приложения доступен пользователю. Backend хранит секрет "
                    "и даёт клиенту безопасный контракт."
                ),
                processing_status=SourceStatus.READY,
            )
            session.add(voice_source)
            await session.flush()
            voiceover = VoiceoverTrack(
                production_project_id=production.id,
                source_item_id=voice_source.id,
                original_path="fixtures/voice.wav",
                processed_path="fixtures/voice.wav",
                duration=8,
                language="ru",
                transcript=voice_source.transcript or "",
                segments=[
                    {
                        "start": 0,
                        "end": 3.2,
                        "text": "Ключ внутри приложения доступен пользователю.",
                    },
                    {
                        "start": 3.5,
                        "end": 8,
                        "text": "Backend хранит секрет и даёт клиенту безопасный контракт.",
                    },
                ],
                words=[],
                script_version_id=script.id,
                status=VoiceoverStatus.READY,
            )
            session.add(voiceover)
            await session.flush()
            production.primary_voiceover_id = voiceover.id
            session.add(
                VisualAsset(
                    project_id=project.id,
                    type=AssetType.SCREENSHOT,
                    status=AssetStatus.READY,
                    original_path="fixtures/app.png",
                    filename="app.png",
                    mime_type="image/png",
                    file_size=10,
                    title="mobile application UI",
                    description=(
                        "specific mobile application interface showing the client relationship"
                    ),
                    tags=["mobile", "application", "UI"],
                )
            )
            await session.commit()
            settings = Settings(
                director_enabled=True,
                ai_provider="mock" if fake else Settings().ai_provider,
                video_font_path="",
                media_root=str(root / "media"),
                render_temp_root=str(root / "render"),
            )
            run = await DirectorRunService(session, settings).start(
                production.id,
                "Сделай понятный технологичный ролик о риске секрета в мобильном клиенте.",
            )
            provider = None if fake else create_ai_provider(settings)
            try:
                run = await AutonomousDirector(session, production.id, settings, provider).run(
                    run, render=not fake
                )
            finally:
                close = getattr(provider, "aclose", None)
                if close is not None:
                    await close()
            actions = list(
                (
                    await session.scalars(
                        select(DirectorAction).where(DirectorAction.run_id == run.id)
                    )
                ).all()
            )
            active_revision = await session.get(
                TimelineRevision, production.active_timeline_revision_id
            )
            report = {
                "status": "passed" if run.status == "completed" else "failed",
                "fake_director": "passed"
                if fake and run.status == "completed"
                else "not_tested"
                if not fake
                else "failed",
                "real_director": "not_tested" if fake else run.status,
                "real_ffmpeg": "not_tested" if fake else "requested",
                "real_tts": "not_tested" if fake else "not_used_by_fixture",
                "real_vision": "not_tested",
                "web_asset_search": "not_tested",
                "run_id": str(run.id),
                "stage": run.status,
                "story_analysis": bool(run.story_analysis_json),
                "director_plan": bool(run.director_plan_json),
                "audio_intelligence": bool(run.audio_intelligence_json),
                "review_iterations": run.review_iterations,
                "metrics": run.metrics_json,
                "error": run.error,
            }
            artifacts = {
                "story-analysis.json": run.story_analysis_json,
                "director-plan.json": run.director_plan_json,
                "audio-intelligence.json": run.audio_intelligence_json,
                "director-actions.json": [item.result for item in actions],
                "rough-timeline.json": active_revision.timeline_json if active_revision else {},
                "critic-report-1.json": run.quality_report_json,
                "director-review-1.json": next(
                    (
                        item.get("director_review", {})
                        for item in reversed(run.history_json or [])
                        if item.get("stage") == "review"
                    ),
                    {},
                ),
                "correction-plan.json": next(
                    (
                        item.get("plan", {})
                        for item in reversed(run.history_json or [])
                        if item.get("stage") == "correction_plan"
                    ),
                    {},
                ),
                "final-timeline.json": active_revision.timeline_json if active_revision else {},
                "final-quality-report.json": run.quality_report_json,
            }
        await engine.dispose()
    await asyncio.to_thread(report_dir.mkdir, parents=True, exist_ok=True)
    await asyncio.to_thread(
        (report_dir / "autonomous-director-report.json").write_text,
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    for filename, payload in artifacts.items():
        await asyncio.to_thread(
            (report_dir / filename).write_text,
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
