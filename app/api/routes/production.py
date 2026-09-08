import uuid

from fastapi import APIRouter, status

from app.api.dependencies import (
    AssemblyDep,
    ProductionMaterialDep,
    ProductionProjectDep,
    ProductionRenderQueueDep,
    ScriptVersionDep,
    TimelineRevisionDep,
    VoiceoverDep,
)
from app.models import ProductionMaterial
from app.schemas.production import (
    MaterialAttach,
    PlacementRequest,
    PlacementSelection,
    ProductionMaterialRead,
    ProductionProjectCreate,
    ProductionProjectRead,
    ReplanRequest,
    ScriptEditRequest,
    ScriptVersionRead,
    TimelineRevisionRead,
    VoiceoverRead,
)
from app.schemas.video import RenderEnqueueResponse

router = APIRouter(prefix="/production-projects", tags=["production-studio"])


@router.post("", response_model=ProductionProjectRead, status_code=status.HTTP_201_CREATED)
async def create_production(data: ProductionProjectCreate, service: ProductionProjectDep) -> object:
    return await service.create(data)


@router.get("/user/{user_id}", response_model=list[ProductionProjectRead])
async def list_productions(user_id: uuid.UUID, service: ProductionProjectDep) -> object:
    return await service.list_for_user(user_id)


@router.get("/telegram-user/{telegram_user_id}", response_model=list[ProductionProjectRead])
async def list_telegram_productions(telegram_user_id: int, service: ProductionProjectDep) -> object:
    return await service.list_for_telegram_user(telegram_user_id)


@router.get("/{production_project_id}", response_model=ProductionProjectRead)
async def get_production(production_project_id: uuid.UUID, service: ProductionProjectDep) -> object:
    return await service.get(production_project_id)


@router.post(
    "/{production_project_id}/materials",
    response_model=ProductionMaterialRead,
    status_code=status.HTTP_201_CREATED,
)
async def attach_material(
    production_project_id: uuid.UUID,
    data: MaterialAttach,
    service: ProductionMaterialDep,
) -> object:
    return await service.attach(production_project_id, data)


@router.get("/{production_project_id}/materials", response_model=list[ProductionMaterialRead])
async def list_materials(
    production_project_id: uuid.UUID, service: ProductionMaterialDep, used: bool | None = None
) -> object:
    return await service.list(production_project_id, used=used)


@router.post("/{production_project_id}/scripts/generate", response_model=ScriptVersionRead)
async def generate_script(production_project_id: uuid.UUID, service: ScriptVersionDep) -> object:
    return await service.generate_v1(production_project_id)


@router.post("/{production_project_id}/scripts/edit", response_model=ScriptVersionRead)
async def edit_script(
    production_project_id: uuid.UUID, data: ScriptEditRequest, service: ScriptVersionDep
) -> object:
    return await service.edit(production_project_id, data.instruction)


@router.get("/{production_project_id}/scripts", response_model=list[ScriptVersionRead])
async def script_history(production_project_id: uuid.UUID, service: ScriptVersionDep) -> object:
    return await service.history(production_project_id)


@router.post(
    "/{production_project_id}/scripts/{script_id}/approve", response_model=ScriptVersionRead
)
async def approve_script(
    production_project_id: uuid.UUID, script_id: uuid.UUID, service: ScriptVersionDep
) -> object:
    version = await service.get(script_id)
    if version.production_project_id != production_project_id:
        from app.services.errors import NotFoundError

        raise NotFoundError("ScriptVersion not found")
    return await service.approve(script_id)


@router.post("/{production_project_id}/voiceovers/{source_item_id}", response_model=VoiceoverRead)
async def promote_voiceover(
    production_project_id: uuid.UUID, source_item_id: uuid.UUID, service: VoiceoverDep
) -> object:
    return await service.create_from_processed_source(production_project_id, source_item_id)


@router.post("/{production_project_id}/assembly", response_model=TimelineRevisionRead)
async def assemble(production_project_id: uuid.UUID, service: AssemblyDep) -> object:
    return await service.assemble(production_project_id)


@router.post("/{production_project_id}/placement")
async def semantic_placement(
    production_project_id: uuid.UUID, data: PlacementRequest, service: AssemblyDep
) -> dict[str, object]:
    placement, revision = await service.insert_locked(
        production_project_id,
        data.material_id,
        data.instruction,
        candidate_index=data.candidate_index,
    )
    return {
        "placement": placement.model_dump(mode="json"),
        "revision": TimelineRevisionRead.model_validate(revision).model_dump(mode="json")
        if revision
        else None,
    }


@router.post("/materials/{material_id}/placement")
async def select_semantic_placement(
    material_id: uuid.UUID, data: PlacementSelection, service: AssemblyDep
) -> dict[str, object]:
    material = await service.session.get(ProductionMaterial, material_id)
    if material is None or not material.user_instruction:
        from app.services.errors import InvalidStateError

        raise InvalidStateError("Material has no pending placement instruction")
    placement, revision = await service.insert_locked(
        material.production_project_id,
        material.id,
        material.user_instruction,
        candidate_index=data.candidate_index,
    )
    return {
        "placement": placement.model_dump(mode="json"),
        "revision": revision.revision_number if revision else None,
    }


@router.post("/{production_project_id}/replan", response_model=TimelineRevisionRead)
async def local_replan(
    production_project_id: uuid.UUID, data: ReplanRequest, service: AssemblyDep
) -> object:
    return await service.local_replan(production_project_id, data.instruction)


@router.get(
    "/{production_project_id}/timeline-revisions", response_model=list[TimelineRevisionRead]
)
async def timeline_history(
    production_project_id: uuid.UUID, service: TimelineRevisionDep
) -> object:
    return await service.history(production_project_id)


@router.post(
    "/{production_project_id}/timeline-revisions/{revision_id}/rollback",
    response_model=TimelineRevisionRead,
)
async def rollback_timeline(
    production_project_id: uuid.UUID,
    revision_id: uuid.UUID,
    service: TimelineRevisionDep,
) -> object:
    return await service.rollback(production_project_id, revision_id)


@router.post("/{production_project_id}/render/{profile}", response_model=RenderEnqueueResponse)
async def render_production(
    production_project_id: uuid.UUID, profile: str, queue: ProductionRenderQueueDep
) -> RenderEnqueueResponse:
    if profile not in {"preview", "final"}:
        from app.services.errors import InvalidStateError

        raise InvalidStateError("Render profile must be preview or final")
    return RenderEnqueueResponse(task_id=queue.enqueue(production_project_id, profile), queued=True)
