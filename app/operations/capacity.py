from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import ContentItem
from app.operations.domain import ContentItemStatus


@dataclass(frozen=True)
class CapacityDecision:
    allowed: bool
    reason: str = ""


class CapacityManager:
    def __init__(self, session: AsyncSession, settings: Settings | None = None) -> None:
        self.session = session
        self.settings = settings or Settings()

    async def check(self, stage: str) -> CapacityDecision:
        mapping = {
            "producer": (
                ContentItemStatus.PRODUCER_RUNNING,
                self.settings.operations_max_producer_concurrency,
            ),
            "director": (
                ContentItemStatus.DIRECTOR_RUNNING,
                self.settings.operations_max_director_concurrency,
            ),
            "render": (
                ContentItemStatus.PREVIEW_READY,
                self.settings.operations_max_render_concurrency,
            ),
        }
        if stage not in mapping:
            return CapacityDecision(True)
        status, limit = mapping[stage]
        count = int(
            await self.session.scalar(
                select(func.count()).select_from(ContentItem).where(ContentItem.status == status)
            )
            or 0
        )
        return CapacityDecision(
            count < limit, f"{stage} capacity full ({count}/{limit})" if count >= limit else ""
        )

    async def pending_render(self) -> int:
        return int(
            await self.session.scalar(
                select(func.count())
                .select_from(ContentItem)
                .where(
                    ContentItem.status.in_(
                        [
                            ContentItemStatus.DIRECTOR_QUEUED,
                            ContentItemStatus.DIRECTOR_RUNNING,
                            ContentItemStatus.PREVIEW_READY,
                        ]
                    )
                )
            )
            or 0
        )
