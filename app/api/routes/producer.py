from __future__ import annotations

import uuid

from fastapi import APIRouter, status

from app.api.dependencies import ProducerDep, ProducerQueueDep
from app.core.config import get_settings
from app.producer.domain import ProducerReport, ProducerStatus
from app.schemas.producer import ProducerRunCreate, ProducerRunRead
from app.services.errors import InvalidStateError

router = APIRouter(prefix="/producer", tags=["producer"])


@router.post("/runs", response_model=ProducerRunRead, status_code=status.HTTP_201_CREATED)
async def create_run(
    data: ProducerRunCreate, producer: ProducerDep, queue: ProducerQueueDep
) -> object:
    if not get_settings().producer_enabled:
        raise InvalidStateError("Producer runtime is disabled")
    run = await producer.create(data)
    if run.status == ProducerStatus.CREATED:
        queue.enqueue(run.id)
    return run


@router.get("/runs/{run_id}", response_model=ProducerRunRead)
async def get_run(run_id: uuid.UUID, producer: ProducerDep) -> object:
    return await producer.get(run_id)


@router.post("/runs/{run_id}/cancel", response_model=ProducerRunRead)
async def cancel_run(run_id: uuid.UUID, producer: ProducerDep) -> object:
    return await producer.cancel(run_id)


@router.post("/runs/{run_id}/resume", response_model=ProducerRunRead)
async def resume_run(run_id: uuid.UUID, producer: ProducerDep, queue: ProducerQueueDep) -> object:
    run = await producer.resume(run_id)
    if run.status not in {ProducerStatus.COMPLETED, ProducerStatus.CANCELLED}:
        queue.enqueue(run.id)
    return run


@router.post("/runs/{run_id}/approve", response_model=ProducerRunRead)
async def approve_run(run_id: uuid.UUID, producer: ProducerDep, queue: ProducerQueueDep) -> object:
    run = await producer.approve(run_id)
    queue.enqueue(run.id)
    return run


@router.get("/runs/{run_id}/report", response_model=ProducerReport)
async def get_report(run_id: uuid.UUID, producer: ProducerDep) -> ProducerReport:
    return await producer.report(run_id)
