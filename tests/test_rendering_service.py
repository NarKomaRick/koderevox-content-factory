import asyncio
from pathlib import Path

import pytest

from app.core.config import Settings
from app.models import VideoProject
from app.models.enums import SourceType, VideoProjectStatus
from app.schemas.api import SourceCreate
from app.schemas.video import EditPlan
from app.services.inbox import InboxService
from app.services.media import MediaProcessingError
from app.services.pause import TimeRange
from app.services.rendering import VideoRenderService
from app.services.video_editor import RenderResult
from app.storage.local import LocalStorage


class FakeMedia:
    async def probe(self, _source: Path) -> dict:
        return {}

    def useful_metadata(self, _probe: dict) -> dict:
        return {"video_codec": "h264", "audio_codec": "aac"}


class NoPauses:
    async def detect(self, _source: Path) -> list[TimeRange]:
        return []


class FakeEditor:
    def __init__(self, fails: bool = False) -> None:
        self.calls = 0
        self.workspace: Path | None = None
        self.fails = fails

    async def render(self, **kwargs) -> RenderResult:
        self.calls += 1
        destination: Path = kwargs["destination"]
        self.workspace = destination.parent
        if self.fails:
            raise MediaProcessingError("raw ffmpeg dump that must not reach users")
        await asyncio.to_thread(destination.write_bytes, b"rendered mp4")
        return RenderResult(destination, 6, 1080, 1920, 12, "h264", "aac")


async def render_fixture(session, tmp_path, editor: FakeEditor):
    storage = LocalStorage(str(tmp_path / "media"))
    source_path = await storage.save("source.mp4", b"source video")
    source, _ = await InboxService(session).register_source(
        SourceCreate(
            telegram_user_id=42,
            telegram_update_id=4000,
            type=SourceType.VIDEO,
            local_file_path=source_path,
            duration_seconds=6,
        )
    )
    source.transcript = "Мы нашли баг с двойным запросом"
    source.transcript_segments = [{"start": 0, "end": 6, "text": "Мы нашли баг с двойным запросом"}]
    plan = EditPlan.model_validate(
        {
            "clips": [
                {"source_start": 0, "source_end": 6, "source_segment_ids": [0], "purpose": "main"}
            ],
            "hook_text": "Двойной запрос",
            "recommended_duration": 6,
            "reasoning_summary": "Ручной тест",
            "framing": "center_crop",
            "pace": "medium",
        }
    )
    project = VideoProject(
        project_id=source.project_id,
        source_item_id=source.id,
        status=VideoProjectStatus.READY_TO_RENDER,
        target_duration=6,
        edit_plan=plan.model_dump(mode="json"),
        subtitle_style={"preset": "tech"},
        render_settings={
            "width": 1080,
            "height": 1920,
            "fps": 30,
            "crf": 20,
            "preset": "medium",
            "remove_pauses": True,
        },
        render_fingerprint="fingerprint",
    )
    session.add(project)
    await session.commit()
    settings = Settings(
        media_root=str(tmp_path / "media"),
        render_temp_root=str(tmp_path / "workspace"),
        video_min_duration=2,
    )
    service = VideoRenderService(
        session=session,
        storage=storage,
        settings=settings,
        editor=editor,  # type: ignore[arg-type]
        media=FakeMedia(),  # type: ignore[arg-type]
        pause_detector=NoPauses(),  # type: ignore[arg-type]
    )
    return service, project, storage


async def test_render_status_metrics_cleanup_and_duplicate_delivery(session, tmp_path) -> None:
    editor = FakeEditor()
    service, project, storage = await render_fixture(session, tmp_path, editor)

    rendered = await service.render(project.id, "fingerprint")
    assert rendered.status == VideoProjectStatus.RENDERED
    assert rendered.metrics["output_duration"] == 6
    assert rendered.final_path and storage.resolve(rendered.final_path).exists()
    assert editor.workspace is not None and not editor.workspace.exists()

    repeated = await service.render(project.id, "fingerprint")
    assert repeated.status == VideoProjectStatus.RENDERED
    assert editor.calls == 1


async def test_render_failure_is_sanitized_and_workspace_is_cleaned(session, tmp_path) -> None:
    editor = FakeEditor(fails=True)
    service, project, _storage = await render_fixture(session, tmp_path, editor)

    with pytest.raises(MediaProcessingError):
        await service.render(project.id, "fingerprint")

    await session.refresh(project)
    assert project.status == VideoProjectStatus.FAILED
    assert (
        project.render_error == "Video processing failed. See application logs for FFmpeg details."
    )
    assert editor.workspace is not None and not editor.workspace.exists()
