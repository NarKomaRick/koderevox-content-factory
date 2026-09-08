import uuid

from fastapi import APIRouter

from app.api.dependencies import VideoProjectDep, VideoQueueDep, VisualPlanDep
from app.schemas.video import (
    ApprovedPackage,
    EditPlanPatch,
    GenerateEditPlanRequest,
    RenderEnqueueResponse,
    RenderRequest,
    StyleUpdate,
    TranscriptOverrideUpdate,
    VideoProjectRead,
)
from app.schemas.visual import (
    ManualVisualInsertion,
    VisualInstructionRequest,
    VisualPlan,
    VisualPlanPatch,
    VisualSuggestionRequest,
)

router = APIRouter(prefix="/video-projects", tags=["video-projects"])


@router.get("/{video_project_id}/visual-plan", response_model=VisualPlan)
async def get_visual_plan(video_project_id: uuid.UUID, service: VisualPlanDep) -> object:
    return await service.get(video_project_id)


@router.put("/{video_project_id}/visual-plan", response_model=VideoProjectRead)
async def replace_visual_plan(
    video_project_id: uuid.UUID, data: VisualPlanPatch, service: VisualPlanDep
) -> object:
    return await service.replace(video_project_id, data.visual_plan)


@router.post("/{video_project_id}/visual-plan/insertions", response_model=VideoProjectRead)
async def add_visual_insertion(
    video_project_id: uuid.UUID, data: ManualVisualInsertion, service: VisualPlanDep
) -> object:
    return await service.add(video_project_id, data.insertion)


@router.delete(
    "/{video_project_id}/visual-plan/insertions/{index}",
    response_model=VideoProjectRead,
)
async def remove_visual_insertion(
    video_project_id: uuid.UUID, index: int, service: VisualPlanDep
) -> object:
    return await service.remove(video_project_id, index)


@router.post("/{video_project_id}/visual-suggestions", response_model=VisualPlan)
async def visual_suggestions(
    video_project_id: uuid.UUID, data: VisualSuggestionRequest, service: VisualPlanDep
) -> object:
    return await service.suggest(video_project_id, data.instruction)


@router.post("/{video_project_id}/visual-plan/instruction", response_model=VideoProjectRead)
async def apply_visual_instruction(
    video_project_id: uuid.UUID,
    data: VisualInstructionRequest,
    service: VisualPlanDep,
) -> object:
    return await service.apply_instruction(video_project_id, data.instruction)


@router.get("", response_model=list[VideoProjectRead])
async def list_video_projects(service: VideoProjectDep) -> object:
    return await service.list()


@router.get("/{video_project_id}", response_model=VideoProjectRead)
async def get_video_project(video_project_id: uuid.UUID, service: VideoProjectDep) -> object:
    return await service.get(video_project_id)


@router.get("/{video_project_id}/approved-package", response_model=ApprovedPackage)
async def approved_package(video_project_id: uuid.UUID, service: VideoProjectDep) -> object:
    return await service.approved_package(video_project_id)


@router.post("/{video_project_id}/generate-edit-plan", response_model=VideoProjectRead)
async def generate_edit_plan(
    video_project_id: uuid.UUID,
    data: GenerateEditPlanRequest,
    service: VideoProjectDep,
) -> object:
    return await service.generate_edit_plan(video_project_id, data.concept_index, data.instruction)


@router.post("/{video_project_id}/regenerate-concepts", response_model=VideoProjectRead)
async def regenerate_video_concepts(
    video_project_id: uuid.UUID, service: VideoProjectDep
) -> object:
    return await service.regenerate_concepts(video_project_id)


@router.patch("/{video_project_id}/edit-plan", response_model=VideoProjectRead)
async def replace_edit_plan(
    video_project_id: uuid.UUID, data: EditPlanPatch, service: VideoProjectDep
) -> object:
    return await service.replace_edit_plan(video_project_id, data.edit_plan)


async def _enqueue_render(
    video_project_id: uuid.UUID,
    force: bool,
    service: VideoProjectDep,
    queue: VideoQueueDep,
) -> RenderEnqueueResponse:
    project, should_queue = await service.prepare_render(video_project_id, force=force)
    if not should_queue:
        return RenderEnqueueResponse(
            task_id=project.render_task_id or "already-rendered", queued=False
        )
    assert project.render_fingerprint is not None
    task_id = queue.enqueue(project.id, project.render_fingerprint)
    await service.set_render_task_id(project.id, task_id)
    return RenderEnqueueResponse(task_id=task_id, queued=True)


@router.post("/{video_project_id}/render", response_model=RenderEnqueueResponse)
async def render_video_project(
    video_project_id: uuid.UUID,
    data: RenderRequest,
    service: VideoProjectDep,
    queue: VideoQueueDep,
) -> RenderEnqueueResponse:
    return await _enqueue_render(video_project_id, data.force, service, queue)


@router.post("/{video_project_id}/rerender", response_model=RenderEnqueueResponse)
async def rerender_video_project(
    video_project_id: uuid.UUID, service: VideoProjectDep, queue: VideoQueueDep
) -> RenderEnqueueResponse:
    return await _enqueue_render(video_project_id, True, service, queue)


@router.post("/{video_project_id}/style", response_model=RenderEnqueueResponse)
async def update_video_style(
    video_project_id: uuid.UUID,
    data: StyleUpdate,
    service: VideoProjectDep,
    queue: VideoQueueDep,
) -> RenderEnqueueResponse:
    await service.update_style(video_project_id, data.preset)
    return await _enqueue_render(video_project_id, True, service, queue)


@router.patch("/{video_project_id}/transcript-overrides", response_model=VideoProjectRead)
async def update_transcript_overrides(
    video_project_id: uuid.UUID,
    data: TranscriptOverrideUpdate,
    service: VideoProjectDep,
) -> object:
    return await service.update_transcript_overrides(video_project_id, data.replacements)


@router.post("/{video_project_id}/approve", response_model=VideoProjectRead)
async def approve_video_project(video_project_id: uuid.UUID, service: VideoProjectDep) -> object:
    return await service.approve(video_project_id)


@router.post("/{video_project_id}/archive", response_model=VideoProjectRead)
async def archive_video_project(video_project_id: uuid.UUID, service: VideoProjectDep) -> object:
    return await service.archive(video_project_id)


@router.post("/{video_project_id}/cancel", response_model=VideoProjectRead)
async def cancel_video_project(video_project_id: uuid.UUID, service: VideoProjectDep) -> object:
    return await service.request_cancel(video_project_id)
