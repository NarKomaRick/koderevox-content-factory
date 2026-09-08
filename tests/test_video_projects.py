from pathlib import Path

from app.ai.mock import MockAIProvider
from app.core.config import Settings
from app.models.enums import SourceStatus, SourceType, SubtitlePreset, VideoProjectStatus
from app.schemas.api import SourceCreate
from app.schemas.video import ManualClipRequest, VideoProjectCreate
from app.services.inbox import InboxService
from app.services.video_projects import VideoProjectService
from app.storage.local import LocalStorage


async def video_source(session, tmp_path):
    storage = LocalStorage(str(tmp_path))
    local_path = await storage.save("source.mp4", b"video")
    source, _ = await InboxService(session).register_source(
        SourceCreate(
            telegram_user_id=42,
            type=SourceType.VIDEO,
            local_file_path=local_path,
            duration_seconds=12.5,
            telegram_update_id=3000,
        )
    )
    source.transcript = "Сегодня обнаружили проблему. 1С получала две записи."
    source.transcript_segments = [
        {"start": 0, "end": 5.2, "text": "Сегодня обнаружили проблему."},
        {"start": 5.2, "end": 12.5, "text": "1С получала две записи."},
    ]
    source.processing_status = SourceStatus.READY
    await session.commit()
    return source


async def test_create_select_render_state_and_archive(session, tmp_path) -> None:
    source = await video_source(session, tmp_path)
    service = VideoProjectService(
        session, MockAIProvider(), Settings(media_root=str(tmp_path), video_min_duration=2)
    )

    project = await service.create_from_source(source.id, VideoProjectCreate())
    assert project.status == VideoProjectStatus.DRAFT
    assert len(project.concepts) == 3

    project = await service.generate_edit_plan(project.id, 0)
    assert project.status == VideoProjectStatus.READY_TO_RENDER
    assert len(project.edit_plan["clips"]) == 2

    project, queued = await service.prepare_render(project.id)
    assert queued is True
    await service.set_render_task_id(project.id, "task-1")
    project.status = VideoProjectStatus.RENDERING
    await session.commit()
    _, queued = await service.prepare_render(project.id)
    assert queued is False

    archived = await service.archive(project.id)
    assert archived.status == VideoProjectStatus.ARCHIVED


async def test_manual_clip_and_approve(session, tmp_path) -> None:
    source = await video_source(session, tmp_path)
    service = VideoProjectService(
        session, MockAIProvider(), Settings(media_root=str(tmp_path), video_min_duration=2)
    )
    project = await service.create_manual(
        source.id, ManualClipRequest(source_start=1, source_end=8, framing="screen_fit")
    )
    assert project.metrics["manual_clip"] is True
    assert project.edit_plan["clips"][0]["source_segment_ids"] == [0, 1]

    project.status = VideoProjectStatus.RENDERED
    project.final_path = str(Path("render") / "final.mp4")
    await session.commit()
    approved = await service.approve(project.id)
    assert approved.status == VideoProjectStatus.APPROVED


async def test_style_change_and_rerender_reuse_the_saved_plan(session, tmp_path) -> None:
    source = await video_source(session, tmp_path)
    service = VideoProjectService(
        session, MockAIProvider(), Settings(media_root=str(tmp_path), video_min_duration=2)
    )
    project = await service.create_manual(
        source.id, ManualClipRequest(source_start=1, source_end=8)
    )
    original_plan = project.edit_plan
    original_fingerprint = project.render_fingerprint
    project.status = VideoProjectStatus.RENDERED
    project.final_path = "render/existing.mp4"
    await session.commit()

    same, queued = await service.prepare_render(project.id, force=False)
    assert queued is False
    assert same.edit_plan == original_plan

    styled = await service.update_style(project.id, SubtitlePreset.DYNAMIC)
    assert styled.status == VideoProjectStatus.READY_TO_RENDER
    assert styled.edit_plan == original_plan
    assert styled.render_fingerprint != original_fingerprint
    _, queued = await service.prepare_render(project.id, force=True)
    assert queued is True
