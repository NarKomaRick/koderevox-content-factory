from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import ContentStrategy, ProducerRun


@dataclass(frozen=True)
class BudgetDecision:
    decision: str
    reason: str = ""


class BudgetManager:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or Settings()

    async def check(
        self, strategy: ContentStrategy, *, now: datetime | None = None
    ) -> BudgetDecision:
        current = now or datetime.now(UTC)
        start = current - timedelta(days=1)
        calls = int(
            await self.session.scalar(
                select(func.coalesce(func.sum(ProducerRun.llm_call_count), 0)).where(
                    ProducerRun.project_id == strategy.project_id, ProducerRun.created_at >= start
                )
            )
            or 0
        )
        limit = int(
            (strategy.budget or {}).get(
                "max_llm_calls_per_day", self.settings.operations_max_llm_calls_per_day
            )
        )
        if calls >= limit:
            return BudgetDecision("defer", "daily LLM-call budget exhausted")
        return BudgetDecision("allow")

    @staticmethod
    def from_values(*, used: int, limit: int) -> BudgetDecision:
        return (
            BudgetDecision("defer", "budget exhausted")
            if used >= limit
            else BudgetDecision("allow")
        )
