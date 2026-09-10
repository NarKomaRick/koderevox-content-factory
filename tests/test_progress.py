from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.bot.handlers import _format_progress_message
from app.models import JobProgress, ProgressEvent
from app.operations.clock import FakeClock
from app.progress import ProgressReporter
from app.progress.eta import ProgressETAEstimator


@pytest.mark.asyncio
async def test_progress_persists_real_stages_and_throttles(session) -> None:
    clock = FakeClock(datetime(2026, 9, 14, 9, tzinfo=UTC))
    reporter = ProgressReporter(
        session,
        "producer",
        "run-1",
        clock=clock,
        min_interval_seconds=20,
    )
    await reporter.report_stage("researching", message="Проверяю источники", force=True)
    clock.advance(seconds=1)
    await reporter.report_stage("researching", progress=0.01, message="ещё проверяю")
    event_count = await session.scalar(select(func.count()).select_from(ProgressEvent))
    assert event_count == 1
    clock.advance(seconds=19)
    await reporter.report_stage("writing_script", message="Пишу сценарий", force=True)
    await reporter.complete()
    row = await session.scalar(
        select(JobProgress).where(JobProgress.job_type == "producer", JobProgress.job_id == "run-1")
    )
    assert row is not None
    assert row.state == "completed"
    assert row.stage == "writing_script"
    completed = (
        await session.scalars(
            select(ProgressEvent).where(ProgressEvent.event_type == "stage_completed")
        )
    ).all()
    assert completed
    assert all(item.duration_seconds is not None for item in completed)


@pytest.mark.asyncio
async def test_progress_heartbeat_updates_liveness_without_fake_stage_progress(session) -> None:
    clock = FakeClock(datetime(2026, 9, 14, 9, tzinfo=UTC))
    reporter = ProgressReporter(session, "producer", "heartbeat-1", clock=clock)
    await reporter.report_stage(
        "researching", progress=0.4, message="Проверяю источники", force=True
    )
    clock.advance(seconds=20)
    await reporter.heartbeat(message="🧠 LLM всё ещё работает над этим этапом")
    row = await session.scalar(
        select(JobProgress).where(
            JobProgress.job_type == "producer", JobProgress.job_id == "heartbeat-1"
        )
    )
    assert row is not None
    assert row.stage == "researching"
    assert row.stage_progress == pytest.approx(0.4)
    assert row.message == "🧠 LLM всё ещё работает над этим этапом"
    assert row.updated_at.replace(tzinfo=UTC) == clock.now()
    events = (await session.scalars(select(ProgressEvent))).all()
    assert len(events) == 1


@pytest.mark.asyncio
async def test_eta_uses_production_history_but_not_fake_history(session) -> None:
    clock = FakeClock(datetime(2026, 9, 14, 9, tzinfo=UTC))
    first = ProgressReporter(session, "producer", "real-1", clock=clock, source_kind="production")
    await first.report_stage("researching", force=True)
    clock.advance(seconds=20)
    await first.report_stage("writing_script", force=True)
    clock.advance(seconds=15)
    await first.complete()
    estimate = await ProgressETAEstimator(session).estimate(["researching", "writing_script"])
    assert estimate.seconds == pytest.approx(35)
    fake = ProgressReporter(session, "producer", "fake-1", clock=clock, source_kind="fake")
    await fake.report_stage("researching", force=True)
    clock.advance(seconds=100)
    await fake.complete()
    fake_estimate = await ProgressETAEstimator(session).estimate(
        ["researching"], source_kind="fake"
    )
    assert fake_estimate.seconds is None


def test_telegram_progress_format_includes_elapsed_without_internal_details() -> None:
    started_at = (datetime.now(UTC) - timedelta(seconds=75)).isoformat()
    message = _format_progress_message(
        "Пишу сценарий",
        "running",
        {
            "started_at": started_at,
            "message": "Формирую сценарий",
        },
        {"overall_progress": 0.37, "estimated_remaining_seconds": None},
    )
    assert "Общий прогресс: 37%" in message
    assert "Прошло: 1 мин" in message
    assert "Формирую сценарий" in message
    assert "system prompt" not in message.lower()
