import uuid

from fastapi import APIRouter, HTTPException, Response, status

from app.api.dependencies import InboxDep, QueueDep, ServiceDep, VideoProjectDep
from app.core.config import get_settings
from app.models.enums import SourceStatus
from app.schemas.api import (
    DraftRead,
    EnqueueResponse,
    IdeaRead,
    SourceCreate,
    SourceNoteCreate,
    SourceNoteRead,
    SourceRead,
    TelegramIngestionResponse,
)
from app.schemas.video import ManualClipRequest, VideoProjectCreate, VideoProjectRead

router = APIRouter(prefix="/sources", tags=["sources"])


@router.get("", response_model=list[SourceRead])
async def list_sources(service: ServiceDep) -> object:
    return await service.list_sources()


@router.post("", response_model=SourceRead, status_code=status.HTTP_201_CREATED)
async def create_source(data: SourceCreate, inbox: InboxDep) -> object:
    source, _created = await inbox.register_source(data)
    return source


@router.post(
    "/telegram-ingestion",
    response_model=TelegramIngestionResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def telegram_ingestion(
    data: SourceCreate, inbox: InboxDep, queue: QueueDep
) -> TelegramIngestionResponse:
    limit = get_settings().max_media_size_mb * 1024 * 1024
    if data.file_size is not None and data.file_size > limit:
        raise HTTPException(status_code=413, detail="Media exceeds configured size limit")
    source, created = await inbox.register_source(data)
    should_queue = created or source.processing_status in {SourceStatus.NEW, SourceStatus.FAILED}
    task_id = queue.enqueue(source.id) if should_queue else None
    return TelegramIngestionResponse(
        source=SourceRead.model_validate(source), created=created, task_id=task_id
    )


@router.get("/{source_id}", response_model=SourceRead)
async def get_source(source_id: uuid.UUID, service: ServiceDep) -> object:
    return await service.get_source(source_id)


@router.post("/{source_id}/generate-ideas", response_model=list[IdeaRead])
async def generate_ideas(source_id: uuid.UUID, service: ServiceDep) -> object:
    return await service.generate_ideas(source_id)


@router.post("/{source_id}/enqueue", response_model=EnqueueResponse)
async def enqueue_source(source_id: uuid.UUID, inbox: InboxDep, queue: QueueDep) -> EnqueueResponse:
    await inbox.get_source(source_id)
    return EnqueueResponse(task_id=queue.enqueue(source_id))


@router.post("/{source_id}/retry", response_model=EnqueueResponse)
async def retry_source(source_id: uuid.UUID, inbox: InboxDep, queue: QueueDep) -> EnqueueResponse:
    await inbox.retry(source_id)
    return EnqueueResponse(task_id=queue.enqueue(source_id))


@router.post("/{source_id}/notes", response_model=SourceNoteRead)
async def add_note(
    source_id: uuid.UUID, data: SourceNoteCreate, inbox: InboxDep, queue: QueueDep
) -> object:
    note = await inbox.add_note(source_id, data)
    if data.telegram_file_id:
        queue.enqueue_note(note.id)
    else:
        queue.enqueue(source_id)
    return note


@router.get("/{source_id}/notes", response_model=list[SourceNoteRead])
async def list_notes(source_id: uuid.UUID, inbox: InboxDep) -> object:
    return await inbox.list_notes(source_id)


@router.post("/{source_id}/archive", response_model=SourceRead)
async def archive_source(source_id: uuid.UUID, inbox: InboxDep) -> object:
    return await inbox.archive(source_id)


@router.post("/{source_id}/generate-short", response_model=DraftRead)
async def generate_short(source_id: uuid.UUID, service: ServiceDep) -> object:
    return await service.generate_short_from_source(source_id)


@router.post("/{source_id}/generate-telegram-post", response_model=DraftRead)
async def generate_telegram_post(source_id: uuid.UUID, service: ServiceDep) -> object:
    return await service.generate_telegram_post_from_source(source_id)


@router.post("/{source_id}/video-projects", response_model=VideoProjectRead)
async def create_video_project(
    source_id: uuid.UUID, data: VideoProjectCreate, service: VideoProjectDep
) -> object:
    return await service.create_from_source(source_id, data)


@router.post("/{source_id}/video-projects/manual", response_model=VideoProjectRead)
async def create_manual_video_project(
    source_id: uuid.UUID, data: ManualClipRequest, service: VideoProjectDep
) -> object:
    return await service.create_manual(source_id, data)


@router.delete("/{source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_source(source_id: uuid.UUID, inbox: InboxDep) -> Response:
    await inbox.delete(source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
