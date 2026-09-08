import uuid

from fastapi import APIRouter
from fastapi.responses import FileResponse

from app.api.dependencies import ThumbnailDep
from app.schemas.thumbnails import ThumbnailGenerateRequest, ThumbnailRead

router = APIRouter(prefix="/thumbnail-projects", tags=["thumbnails"])


@router.get("/{thumbnail_id}", response_model=ThumbnailRead)
async def get_thumbnail(thumbnail_id: uuid.UUID, service: ThumbnailDep) -> object:
    return await service.get(thumbnail_id)


@router.get("/{thumbnail_id}/file")
async def get_thumbnail_file(thumbnail_id: uuid.UUID, service: ThumbnailDep) -> FileResponse:
    thumbnail = await service.get(thumbnail_id)
    if not thumbnail.output_path:
        from app.services.errors import InvalidStateError

        raise InvalidStateError("Thumbnail has no rendered file")
    return FileResponse(
        service.storage.resolve(thumbnail.output_path),
        media_type="image/jpeg",
        filename=f"{thumbnail.id}.jpg",
    )


@router.get("", response_model=list[ThumbnailRead])
async def list_thumbnails(video_project_id: uuid.UUID, service: ThumbnailDep) -> object:
    return await service.list(video_project_id)


@router.post("/video-projects/{video_project_id}", response_model=list[ThumbnailRead])
async def generate_thumbnails(
    video_project_id: uuid.UUID, data: ThumbnailGenerateRequest, service: ThumbnailDep
) -> object:
    return await service.generate(video_project_id, data.headline)


@router.post("/{thumbnail_id}/select", response_model=ThumbnailRead)
async def select_thumbnail(thumbnail_id: uuid.UUID, service: ThumbnailDep) -> object:
    return await service.select(thumbnail_id)
