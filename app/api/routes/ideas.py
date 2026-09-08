import uuid

from fastapi import APIRouter

from app.api.dependencies import ServiceDep
from app.schemas.api import DraftRead, IdeaRead

router = APIRouter(prefix="/ideas", tags=["ideas"])


@router.get("", response_model=list[IdeaRead])
async def list_ideas(service: ServiceDep) -> object:
    return await service.list_ideas()


@router.get("/{idea_id}", response_model=IdeaRead)
async def get_idea(idea_id: uuid.UUID, service: ServiceDep) -> object:
    return await service.get_idea(idea_id)


@router.post("/{idea_id}/generate-draft", response_model=DraftRead)
async def generate_draft(idea_id: uuid.UUID, service: ServiceDep) -> object:
    return await service.generate_draft(idea_id)
