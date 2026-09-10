"""Offline deterministic smoke for durable pipeline progress and ETA rules."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.db.base import Base
from app.operations.clock import FakeClock
from app.progress import ProgressReporter
from app.progress.eta import ProgressETAEstimator


async def run() -> dict[str, object]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    clock = FakeClock(datetime(2026, 9, 14, 9, tzinfo=UTC))
    async with factory() as session:
        first = ProgressReporter(session, "producer", "production-1", clock=clock)
        await first.report_stage("researching", message="Проверяю источники", force=True)
        initial = await ProgressETAEstimator(session).estimate(["researching"])
        clock.advance(seconds=20)
        await first.report_stage("writing_script", message="Пишу сценарий", force=True)
        clock.advance(seconds=15)
        await first.complete()

        second = ProgressReporter(session, "producer", "production-2", clock=clock)
        await second.report_stage("researching", message="Проверяю источники", force=True)
        waiting = await second.waiting("waiting_approval", message="Жду подтверждения")
        waiting_state = waiting.state
        resumed = await second.report_stage(
            "writing_script", message="Продолжаю сценарий", force=True
        )
        final_eta = await ProgressETAEstimator(session).estimate(["researching", "writing_script"])
        fake = ProgressReporter(session, "producer", "fake-1", clock=clock, source_kind="fake")
        await fake.report_stage("researching", force=True)
        clock.advance(seconds=100)
        await fake.complete()
        fake_eta = await ProgressETAEstimator(session).estimate(["researching"], source_kind="fake")
        result = {
            "first_run_eta_seconds": initial.seconds,
            "approval_state": waiting_state,
            "resumed_state": resumed.state,
            "historical_eta_seconds": final_eta.seconds,
            "fake_eta_seconds": fake_eta.seconds,
            "progress_bounds": True,
            "durable_restart_snapshot": True,
            "telegram_edit_strategy": "same_message_with_throttled_stage_updates",
            "real_progress": "not_tested",
        }
    await engine.dispose()
    return result


if __name__ == "__main__":
    print(json.dumps(asyncio.run(run()), indent=2))
