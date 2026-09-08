import uuid

from fastapi import APIRouter, Response, status

from app.api.dependencies import ServiceDep
from app.schemas.api import DraftRead, DraftStatusUpdate

router = APIRouter(prefix="/drafts", tags=["drafts"])


@router.get("", response_model=list[DraftRead])
async def list_drafts(service: ServiceDep) -> object:
    return await service.list_drafts()


@router.get("/{draft_id}", response_model=DraftRead)
async def get_draft(draft_id: uuid.UUID, service: ServiceDep) -> object:
    return await service.get_draft(draft_id)


@router.patch("/{draft_id}/status", response_model=DraftRead)
async def update_status(
    draft_id: uuid.UUID, data: DraftStatusUpdate, service: ServiceDep
) -> object:
    return await service.update_draft_status(draft_id, data.status)


@router.post("/{draft_id}/regenerate", response_model=DraftRead)
async def regenerate(draft_id: uuid.UUID, service: ServiceDep) -> object:
    draft = await service.get_draft(draft_id)
    return await service.generate_draft(draft.idea_id)


@router.post("/{draft_id}/repurpose", response_model=list[DraftRead])
async def repurpose(draft_id: uuid.UUID, service: ServiceDep) -> object:
    return await service.repurpose(draft_id)


@router.delete("/{draft_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_draft(draft_id: uuid.UUID, service: ServiceDep) -> Response:
    await service.delete_draft(draft_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
