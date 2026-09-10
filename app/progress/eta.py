from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ProgressEvent


@dataclass(frozen=True)
class ETAEstimate:
    seconds: float | None
    confidence: str


class ProgressETAEstimator:
    """Small robust timing estimator; fake samples are never eligible."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def estimate(self, stages: list[str], *, source_kind: str = "production") -> ETAEstimate:
        if source_kind == "fake" or not stages:
            return ETAEstimate(None, "none")
        rows = (
            await self.session.scalars(
                select(ProgressEvent).where(
                    ProgressEvent.event_type == "stage_completed",
                    ProgressEvent.source_kind == source_kind,
                    ProgressEvent.stage.in_(stages),
                    ProgressEvent.duration_seconds.is_not(None),
                )
            )
        ).all()
        durations: dict[str, list[float]] = {stage: [] for stage in stages}
        for row in rows:
            if row.duration_seconds is not None and row.duration_seconds >= 0:
                durations.setdefault(row.stage, []).append(row.duration_seconds)
        if not any(durations.values()):
            return ETAEstimate(None, "none")
        values = [median(items) for items in durations.values() if items]
        confidence = (
            "high" if min(len(items) for items in durations.values() if items) >= 5 else "low"
        )
        return ETAEstimate(sum(values), confidence)
