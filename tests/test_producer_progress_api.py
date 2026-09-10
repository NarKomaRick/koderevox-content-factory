from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.main import app
from app.models import JobProgress, Project, User
from app.producer.runtime import ProducerService
from app.progress.service import JobProgressRead
from app.schemas.producer import ProducerRunCreate


@pytest.mark.asyncio
async def test_attach_progress_message_returns_serializable_snapshot(session, monkeypatch) -> None:
    user = User(telegram_id=90210)
    session.add(user)
    await session.commit()
    project = await session.scalar(select(Project))
    assert project is not None
    run = await ProducerService(session).create(
        ProducerRunCreate(
            prompt="Проверить прогресс",
            user_id=user.id,
            project_id=project.id,
            idempotency_key=f"progress-{uuid.uuid4()}",
        )
    )

    from app.api.dependencies import get_producer_service

    async def override_producer_service():
        return ProducerService(session)

    monkeypatch.setitem(app.dependency_overrides, get_producer_service, override_producer_service)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                f"/producer/runs/{run.id}/progress-message",
                json={"chat_id": 42, "message_id": 7},
            )
        assert response.status_code == 200
        snapshot = JobProgressRead.model_validate(response.json())
        assert snapshot.job_id == str(run.id)
        assert snapshot.state == "created"
        row = await session.scalar(
            select(JobProgress).where(JobProgress.job_id == str(run.id))
        )
        assert row is not None
        assert row.telegram_message_id == 7
    finally:
        app.dependency_overrides.pop(get_producer_service, None)
