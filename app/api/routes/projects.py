from fastapi import APIRouter, status

from app.api.dependencies import ServiceDep
from app.schemas.api import ProjectCreate, ProjectRead

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=list[ProjectRead])
async def list_projects(service: ServiceDep) -> object:
    return await service.list_projects()


@router.post("", response_model=ProjectRead, status_code=status.HTTP_201_CREATED)
async def create_project(data: ProjectCreate, service: ServiceDep) -> object:
    return await service.create_project(data)
