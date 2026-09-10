import uuid

from fastapi import APIRouter, Query, status

from app.api.dependencies import (
    AssemblyDep,
    AutonomousDirectorQueueDep,
    DirectorDep,
    DirectorQueueDep,
    ProductionMaterialDep,
    ProductionProjectDep,
    ProductionRenderQueueDep,
    ScriptVersionDep,
    TimelineRevisionDep,
    VoiceoverDep,
)
from app.core.config import get_settings
from app.director.runtime import DirectorRuntime
from app.director.schemas import (
    DirectorInstructionRequest,
    DirectorRunRead,
    DirectorRunRequest,
    OutputProfile,
)
from app.models import ProductionMaterial, TimelineRevision
from app.quality.visual_critic import DeterministicVisualCritic
from app.schemas.production import (
    MaterialAttach,
    PlacementRequest,
    PlacementSelection,
    ProductionMaterialRead,
    ProductionProjectCreate,
    ProductionProjectRead,
    ProductionTimeline,
    ReplanRequest,
    ScriptEditRequest,
    ScriptVersionRead,
    TimelineRevisionRead,
    VoiceoverRead,
)
from app.schemas.video import RenderEnqueueResponse
from app.services.errors import InvalidStateError, NotFoundError

router = APIRouter(prefix="/production-projects", tags=["production-studio"])


@router.post("", response_model=ProductionProjectRead, status_code=status.HTTP_201_CREATED)
async def create_production(data: ProductionProjectCreate, service: ProductionProjectDep) -> object:
    return await service.create(data)


@router.post("/{production_project_id}/director/run", response_model=DirectorRunRead)
async def run_director(
    production_project_id: uuid.UUID,
    data: DirectorRunRequest,
    director: DirectorDep,
    queue: DirectorQueueDep,
) -> object:
    if not get_settings().director_enabled:
        raise InvalidStateError("Director runtime is disabled")
    run = await director.start(
        production_project_id, data.instruction, profile_name=data.output_profile
    )
    queue.enqueue(run.id)
    return run


@router.post("/{production_project_id}/director/autonomous", response_model=DirectorRunRead)
async def run_autonomous_director(
    production_project_id: uuid.UUID,
    data: DirectorRunRequest,
    director: DirectorDep,
    queue: AutonomousDirectorQueueDep,
) -> object:
    if not get_settings().director_enabled:
        raise InvalidStateError("Director runtime is disabled")
    run = await director.start(
        production_project_id, data.instruction, profile_name=data.output_profile
    )
    queue.enqueue(run.id)
    return run


@router.post("/{production_project_id}/director/instruct", response_model=DirectorRunRead)
async def instruct_director(
    production_project_id: uuid.UUID,
    data: DirectorInstructionRequest,
    director: DirectorDep,
    queue: DirectorQueueDep,
) -> object:
    if not get_settings().director_enabled:
        raise InvalidStateError("Director runtime is disabled")
    run = await director.start(production_project_id, data.instruction)
    queue.enqueue(run.id)
    return run


@router.get("/{production_project_id}/director/status", response_model=DirectorRunRead)
async def director_status(production_project_id: uuid.UUID, director: DirectorDep) -> object:
    run = await director.status(production_project_id)
    if run is None:
        raise NotFoundError("Director run not found")
    return run


@router.post("/{production_project_id}/preview", response_model=RenderEnqueueResponse)
async def director_preview(
    production_project_id: uuid.UUID,
    queue: ProductionRenderQueueDep,
) -> RenderEnqueueResponse:
    return RenderEnqueueResponse(
        task_id=queue.enqueue(production_project_id, "preview"), queued=True
    )


@router.get("/{production_project_id}/quality")
async def production_quality(
    production_project_id: uuid.UUID, director: DirectorDep
) -> dict[str, object]:
    context = await DirectorRuntime(
        director.session, production_project_id, director.settings
    ).context()
    timeline_data = context["timeline"]
    if not timeline_data.get("revision_id"):
        raise NotFoundError("Active timeline not found")
    revision = await director.session.get(TimelineRevision, timeline_data["revision_id"])
    if revision is None:
        raise NotFoundError("Active timeline not found")
    timeline = ProductionTimeline.model_validate(revision.timeline_json)
    profile = OutputProfile.model_validate(context["platform"])
    return DeterministicVisualCritic(director.settings).evaluate(timeline, profile)


@router.get("/{production_project_id}/assets/search")
async def search_production_assets(
    production_project_id: uuid.UUID,
    director: DirectorDep,
    description: str = Query(min_length=2, max_length=1000),
) -> dict[str, object]:
    # This endpoint intentionally searches only imported/cached project assets.
    result = await DirectorRuntime(
        director.session, production_project_id, director.settings
    ).execute("find_visuals", {"description": description})
    if not result.ok:
        raise InvalidStateError(result.error["message"] if result.error else "Asset search failed")
    return result.data


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
