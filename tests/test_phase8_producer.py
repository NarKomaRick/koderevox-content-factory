from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.models import ProductionProject, Project, User
from app.producer.domain import ProducerStatus
from app.producer.research import extract_html, fixture_sources, validate_safe_url
from app.producer.runtime import ProducerRuntime, ProducerService
from app.schemas.producer import ProducerRunCreate
from app.services.errors import PermanentProcessingError


def test_research_url_normalization_and_html_extraction() -> None:
    text, metadata = extract_html(
        "<html><head><title>Title</title><script>ignore()</script></head>"
        "<body><nav>menu</nav><main>Useful <b>fact</b>.</main></body></html>"
    )
    assert "Useful" in text and "fact" in text
    assert metadata["title"] == "Title"
    assert fixture_sources()[0].final_url.endswith("source-a")


@pytest.mark.asyncio
async def test_fake_producer_completes_and_materializes_handoff(session) -> None:
    user = User(telegram_id=12345)
    session.add(user)
    await session.commit()
    project = await session.scalar(select(Project))
    assert project is not None
    run = await ProducerService(session, Settings(producer_enabled=True)).create(
        ProducerRunCreate(
            prompt="Сделать объяснение архитектуры",
            user_id=user.id,
            project_id=project.id,
            idempotency_key="phase8-test-1",
        )
    )
    result = await ProducerRuntime(session, Settings(producer_enabled=True)).run(run.id)
    assert result.status == ProducerStatus.COMPLETED
    assert result.production_project_id is not None
    production = await session.get(ProductionProject, result.production_project_id)
    assert production is not None
    assert production.current_script_version_id is not None
    assert production.production_context["producer_handoff"]["asset_plan"]["requirements"]


@pytest.mark.asyncio
async def test_approval_mode_is_resumable(session) -> None:
    user = User(telegram_id=12346)
    session.add(user)
    await session.commit()
    project = await session.scalar(select(Project))
    assert project is not None
    service = ProducerService(session, Settings(producer_enabled=True))
    run = await service.create(
        ProducerRunCreate(
            prompt="Подготовить короткий ролик",
            user_id=user.id,
            project_id=project.id,
            approval_mode=True,
        )
    )
    runtime = ProducerRuntime(session, Settings(producer_enabled=True))
    waiting = await runtime.run(run.id)
    assert waiting.status == ProducerStatus.REVIEWING_SCRIPT
    assert waiting.approval_state == "pending"
    await runtime.approve(run.id)
    completed = await runtime.run(run.id)
    assert completed.status == ProducerStatus.COMPLETED


def test_fixture_has_time_sensitive_and_injection_cases() -> None:
    rows = fixture_sources()
    assert any("Ignore previous" in row.text for row in rows)
    assert any(row.published_at and row.published_at < datetime.now(UTC) for row in rows)


@pytest.mark.parametrize("url", ["file:///tmp/a", "ftp://example.com/a", "http://127.0.0.1/a"])
def test_research_url_security(url: str) -> None:
    with pytest.raises(PermanentProcessingError):
        validate_safe_url(url)
