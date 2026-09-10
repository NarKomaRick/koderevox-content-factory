from __future__ import annotations

from datetime import UTC, datetime

from app.models import ContentCampaign, ContentItem
from app.operations.domain import ManualPriority


class PriorityResolver:
    manual = {
        ManualPriority.URGENT: 100,
        ManualPriority.HIGH: 80,
        ManualPriority.NORMAL: 50,
        ManualPriority.LOW: 20,
    }

    @classmethod
    def resolve(
        cls,
        item: ContentItem,
        campaign: ContentCampaign | None = None,
        *,
        now: datetime | None = None,
    ) -> int:
        current = now or datetime.now(UTC)
        score = cls.manual.get(ManualPriority(item.manual_priority), 50)
        if campaign:
            score += round(campaign.priority * 0.35)
        if item.scheduled_for:
            hours = (item.scheduled_for - current).total_seconds() / 3600
            if hours <= 24:
                score += 20
            elif hours <= 72:
                score += 10
        if item.retry_count:
            score += min(10, item.retry_count * 3)
        return min(100, max(0, score))
