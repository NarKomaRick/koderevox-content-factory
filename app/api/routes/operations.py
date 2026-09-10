from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.dependencies import get_operations_service
from app.operations.approvals import ApprovalManager
from app.operations.domain import ApprovalStatus, ContentItemStatus
from app.operations.orchestrator import StudioOrchestrator
from app.operations.schemas import (
    ApprovalDecision,
    ApprovalRead,
    CampaignCreate,
    ContentItemCreate,
    ContentItemPatch,
    ContentItemRead,
    SeriesCreate,
    StrategyCreate,
    StrategyPatch,
    StrategyRead,
)
from app.operations.service import OperationsService
from app.progress import PipelineProgressService

router = APIRouter(prefix="/operations", tags=["operations"])
ServiceDep = Annotated[OperationsService, Depends(get_operations_service)]


@router.post("/strategies", response_model=StrategyRead, status_code=status.HTTP_201_CREATED)
async def create_strategy(data: StrategyCreate, service: ServiceDep) -> object:
    return await service.create_strategy(data)


@router.get("/strategies", response_model=list[StrategyRead])
async def list_strategies(service: ServiceDep, project_id: uuid.UUID | None = None) -> object:
    return await service.list_strategies(project_id)


@router.get("/strategies/{strategy_id}", response_model=StrategyRead)
async def get_strategy(strategy_id: uuid.UUID, service: ServiceDep) -> object:
    return await service.get_strategy(strategy_id)


@router.patch("/strategies/{strategy_id}", response_model=StrategyRead)
async def update_strategy(
    strategy_id: uuid.UUID, data: StrategyPatch, service: ServiceDep
) -> object:
    return await service.update_strategy(strategy_id, data)


@router.post("/campaigns", status_code=status.HTTP_201_CREATED)
async def create_campaign(data: CampaignCreate, service: ServiceDep) -> object:
    return await service.create_campaign(data)


@router.post("/series", status_code=status.HTTP_201_CREATED)
async def create_series(data: SeriesCreate, service: ServiceDep) -> object:
    return await service.create_series(data)


@router.post("/items", response_model=ContentItemRead, status_code=status.HTTP_201_CREATED)
async def create_item(data: ContentItemCreate, service: ServiceDep) -> object:
    return await service.create_item(data)


@router.get("/items", response_model=list[ContentItemRead])
async def list_items(
    service: ServiceDep,
    strategy_id: uuid.UUID | None = None,
    item_status: ContentItemStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
) -> object:
    return await service.list_items(
        strategy_id=strategy_id, status=item_status, limit=limit, offset=offset
    )


@router.get("/items/{item_id}", response_model=ContentItemRead)
async def get_item(item_id: uuid.UUID, service: ServiceDep) -> object:
    return await service.get_item(item_id)


@router.get("/items/{item_id}/progress")
async def item_progress(item_id: uuid.UUID, service: ServiceDep) -> object:
    return await PipelineProgressService(service.session).for_item(item_id)


@router.patch("/items/{item_id}", response_model=ContentItemRead)
async def patch_item(item_id: uuid.UUID, data: ContentItemPatch, service: ServiceDep) -> object:
    return await service.patch_item(item_id, data)


@router.post("/items/{item_id}/retry", response_model=ContentItemRead)
async def retry_item(item_id: uuid.UUID, service: ServiceDep) -> object:
    return await service.retry_item(item_id)


@router.post("/items/{item_id}/cancel", response_model=ContentItemRead)
async def cancel_item(item_id: uuid.UUID, service: ServiceDep) -> object:
    return await service.cancel_item(item_id)


@router.post("/items/{item_id}/pause", response_model=ContentItemRead)
async def pause_item(item_id: uuid.UUID, service: ServiceDep) -> object:
    return await service.set_paused(item_id, True)


@router.post("/items/{item_id}/resume", response_model=ContentItemRead)
async def resume_item(item_id: uuid.UUID, service: ServiceDep) -> object:
    return await service.set_paused(item_id, False)


@router.post("/strategies/{strategy_id}/plan")
async def plan_strategy(strategy_id: uuid.UUID, service: ServiceDep) -> object:
    from app.operations.planner import ContentPlanner

    return await ContentPlanner(
        service.session, clock=service.clock, policy=service.policy
    ).plan_strategy(strategy_id)


@router.post("/tick")
async def operations_tick(service: ServiceDep) -> object:
    return await StudioOrchestrator(
        service.session, service.settings, clock=service.clock
    ).run_once()


@router.get("/status")
async def operations_status(service: ServiceDep) -> object:
    return await StudioOrchestrator(service.session, service.settings, clock=service.clock).status()


@router.get("/calendar", response_model=list[ContentItemRead])
async def calendar(
    service: ServiceDep,
    start: datetime | None = None,
    end: datetime | None = None,
    strategy_id: uuid.UUID | None = None,
) -> object:
    return await service.calendar(start=start, end=end, strategy_id=strategy_id)


@router.get("/approvals", response_model=list[ApprovalRead])
async def approvals(
    service: ServiceDep,
    approval_status: ApprovalStatus | None = Query(default=None, alias="status"),
) -> object:
    return await service.approvals(approval_status)


@router.post("/approvals/{approval_id}/approve", response_model=ApprovalRead)
async def approve(approval_id: uuid.UUID, data: ApprovalDecision, service: ServiceDep) -> object:
    return await ApprovalManager(service.session, policy=service.policy).decide(
        approval_id, approved=True, data=data
    )


@router.post("/approvals/{approval_id}/reject", response_model=ApprovalRead)
async def reject(approval_id: uuid.UUID, data: ApprovalDecision, service: ServiceDep) -> object:
    return await ApprovalManager(service.session, policy=service.policy).decide(
        approval_id, approved=False, data=data
    )
