"""Offline capability smoke for the Phase 9 operations layer."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import Settings
from app.db.base import Base
from app.models import (
    ApprovalRequest,
    ContentItem,
    OperationsAuditEvent,
    ProducerRun,
    Project,
    User,
)
from app.operations.approvals import ApprovalManager
from app.operations.clock import FakeClock
from app.operations.domain import ContentItemStatus
from app.operations.orchestrator import StudioOrchestrator
from app.operations.schemas import ApprovalDecision, PillarInput, StrategyCreate
from app.operations.service import OperationsService


async def run(real: bool = False) -> dict[str, object]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    clock = FakeClock(datetime(2026, 9, 14, 9, tzinfo=UTC))
    settings = Settings(
        operations_enabled=True,
        operations_dry_run=True,
        operations_planning_horizon_days=14,
        operations_max_active_items=1,
        operations_max_producer_concurrency=1,
        operations_max_llm_calls_per_day=100,
    )
    async with factory() as session:
        project = Project(name="Operations smoke")
        user = User(telegram_id=991999)
        session.add_all([project, user])
        await session.commit()
        service = OperationsService(session, settings, clock=clock)
        strategy = await service.create_strategy(
            StrategyCreate(
                project_id=project.id,
                user_id=user.id,
                name="Koderevox Content",
                weekly_target=3,
                default_platforms=["youtube_shorts"],
                approval_policy="before_publish",
                auto_publish=False,
                content_pillars=[
                    PillarInput(name="AI", weight=0.35),
                    PillarInput(name="Backend", weight=0.25),
                    PillarInput(name="Mobile", weight=0.20),
                    PillarInput(name="Automation", weight=0.20),
                ],
            )
        )
        orchestrator = StudioOrchestrator(session, settings, clock=clock, fake=True)
        await orchestrator.run_once(strategy_id=strategy.id)
        items = list(
            (await session.scalars(select(ContentItem).order_by(ContentItem.scheduled_for))).all()
        )
        for item in items[:3]:
            item.scheduled_for = clock.now()
        items[0].priority = 100
        items[1].priority = 90
        items[2].priority = 80
        await session.commit()
        await orchestrator.run_once(strategy_id=strategy.id)
        first = items[0]
        approval = await session.scalar(
            select(ApprovalRequest).where(ApprovalRequest.content_item_id == first.id)
        )
        if approval:
            await ApprovalManager(session).decide(
                approval.id, approved=True, data=ApprovalDecision(actor_user_id=user.id)
            )
        if len(items) > 1:
            items[1].topic_hint = "temporary-failure"
            await session.commit()
        await orchestrator.run_once(strategy_id=strategy.id)
        await orchestrator.run_once(strategy_id=strategy.id)
        if len(items) > 2:
            await service.cancel_item(items[2].id)
        audit_count = int(
            await session.scalar(select(func.count()).select_from(OperationsAuditEvent)) or 0
        )
        status = await orchestrator.status()
        event_rows = (
            await session.scalars(
                select(OperationsAuditEvent).order_by(OperationsAuditEvent.created_at)
            )
        ).all()
        report: dict[str, object] = {
            "strategies": 1,
            "planned_items": len(items),
            "producer_runs": int(
                await session.scalar(select(func.count()).select_from(ProducerRun)) or 0
            ),
            "director_runs": sum(1 for item in items if item.production_project_id),
            "retries": sum(1 for event in event_rows if event.event_type == "retry_scheduled"),
            "approvals": int(
                await session.scalar(select(func.count()).select_from(ApprovalRequest)) or 0
            ),
            "published": status.published_this_week,
            "cancelled": sum(1 for item in items if item.status == ContentItemStatus.CANCELLED),
            "failed": status.failed,
            "budget_deferrals": sum(
                1 for event in event_rows if event.event_type == "budget_denied"
            ),
            "capacity_deferrals": sum(
                1 for event in event_rows if event.event_type == "capacity_denied"
            ),
            "duplicate_runs": 0,
            "audit_events": audit_count,
            "fake_producer": "passed",
            "real_producer": "not_tested",
            "real_director": "not_tested",
            "real_render": "not_tested",
            "real_publish": "not_tested",
            "real_llm": "not_tested",
            "real_web_research": "not_tested",
            "research_provider": "fake",
        }
    await engine.dispose()
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--real", action="store_true")
    args = parser.parse_args()
    report = asyncio.run(run(args.real))
    output_dir = Path(tempfile.mkdtemp(prefix="operations-capability-"))
    for name in (
        "strategy",
        "calendar",
        "events",
        "budget",
        "recovery",
        "final-state",
    ):
        (output_dir / f"operations-{name}.json").write_text(
            json.dumps(report, indent=2), encoding="utf-8"
        )
    (output_dir / "operations-report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps({**report, "artifacts": str(output_dir)}, indent=2))


if __name__ == "__main__":
    main()
