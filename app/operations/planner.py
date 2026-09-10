from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import ContentCampaign, ContentItem, ContentStrategy, ContentStrategyPillar
from app.operations.audit import audit
from app.operations.clock import Clock, SystemClock
from app.operations.domain import ContentItemStatus, ManualPriority
from app.operations.policies import OperationsPolicy
from app.operations.priorities import PriorityResolver
from app.operations.schemas import ContentItemRead, PlannerResult
from app.operations.strategist import FakeStrategist


class ContentPlanner:
    def __init__(
        self,
        session: AsyncSession,
        *,
        clock: Clock | None = None,
        policy: OperationsPolicy | None = None,
    ) -> None:
        self.session = session
        self.clock = clock or SystemClock()
        self.policy = policy or OperationsPolicy.from_settings(get_settings())

    async def plan_strategy(self, strategy_id: uuid.UUID) -> PlannerResult:
        strategy = await self.session.get(ContentStrategy, strategy_id)
        if strategy is None:
            raise ValueError("ContentStrategy not found")
        if not strategy.enabled or strategy.paused:
            return PlannerResult(warnings=["strategy is disabled or paused"])
        now = self.clock.now()
        existing_count = int(
            await self.session.scalar(
                select(func.count())
                .select_from(ContentItem)
                .where(
                    ContentItem.strategy_id == strategy.id,
                    ContentItem.status.not_in(
                        [ContentItemStatus.ARCHIVED, ContentItemStatus.CANCELLED]
                    ),
                )
            )
            or 0
        )
        available = max(0, self.policy.max_planned_items - existing_count)
        if not available:
            return PlannerResult(warnings=["planning item limit reached"])
        slots = self._slots(strategy, now)
        existing_slots = {
            (item.scheduled_for, item.idempotency_key)
            for item in (
                await self.session.scalars(
                    select(ContentItem).where(ContentItem.strategy_id == strategy.id)
                )
            ).all()
        }
        pillars = (
            await self.session.scalars(
                select(ContentStrategyPillar).where(
                    ContentStrategyPillar.strategy_id == strategy.id,
                    ContentStrategyPillar.enabled.is_(True),
                )
            )
        ).all()
        campaigns = (
            await self.session.scalars(
                select(ContentCampaign).where(
                    ContentCampaign.strategy_id == strategy.id,
                    ContentCampaign.enabled.is_(True),
                    ContentCampaign.paused.is_(False),
                )
            )
        ).all()
        recent_counts = await self._recent_counts(strategy.id)
        suggestions = FakeStrategist().suggest([pillar.name for pillar in pillars])
        suggestions_by_pillar = {candidate.pillar: candidate for candidate in suggestions}
        created: list[ContentItem] = []
        for slot in slots[:available]:
            key = f"strategy:{strategy.id}:slot:{slot.isoformat()}"
            if any(item[1] == key for item in existing_slots):
                continue
            campaign = self._campaign_for_slot(campaigns, slot)
            pillar = self._choose_pillar(pillars, recent_counts, campaign)
            candidate = suggestions_by_pillar.get(pillar) if pillar else None
            item = ContentItem(
                strategy_id=strategy.id,
                project_id=strategy.project_id,
                user_id=strategy.user_id,
                campaign_id=campaign.id if campaign else None,
                topic_hint=candidate.topic if candidate else None,
                pillar=pillar,
                status=ContentItemStatus.PLANNED,
                priority=50,
                manual_priority=ManualPriority.NORMAL,
                scheduled_for=slot,
                target_platforms=strategy.default_platforms,
                approval_state="not_required",
                idempotency_key=key,
                resource_estimate={"llm_calls": 8, "research_searches": 2, "category": "medium"},
            )
            item.priority = PriorityResolver.resolve(item, campaign, now=now)
            self.session.add(item)
            await self.session.flush()
            await audit(
                self.session,
                "content_planned",
                strategy_id=strategy.id,
                project_id=strategy.project_id,
                content_item_id=item.id,
                rationale="bounded calendar slot and weighted pillar selection",
                data={"pillar": pillar, "campaign_id": str(campaign.id) if campaign else None},
            )
            created.append(item)
            if pillar:
                recent_counts[pillar] = recent_counts.get(pillar, 0) + 1
        await self.session.commit()
        return PlannerResult(
            items_to_create=[ContentItemRead.model_validate(item) for item in created], warnings=[]
        )

    def _slots(self, strategy: ContentStrategy, now: datetime) -> list[datetime]:
        zone = ZoneInfo(strategy.timezone)
        local = now.astimezone(zone)
        rule = strategy.recurrence_rule or {}
        days = rule.get("days")
        if not isinstance(days, list) or not days:
            days = [index for index in range(7) if index < strategy.weekly_target]
        hour, minute = 18, 0
        raw_time = str(rule.get("time", "18:00"))
        try:
            hour, minute = (int(part) for part in raw_time.split(":", 1))
        except ValueError:
            pass
        slots: list[datetime] = []
        for offset in range(self.policy.planning_horizon_days + 1):
            day = local.date() + timedelta(days=offset)
            if day.weekday() in days:
                candidate = datetime.combine(day, time(hour, minute), tzinfo=zone).astimezone(UTC)
                if candidate >= now:
                    slots.append(candidate)
        weeks = max(1, (self.policy.planning_horizon_days + 6) // 7)
        return slots[: strategy.weekly_target * weeks]

    async def _recent_counts(self, strategy_id: uuid.UUID) -> dict[str, int]:
        rows = (
            await self.session.scalars(
                select(ContentItem)
                .where(ContentItem.strategy_id == strategy_id)
                .order_by(ContentItem.created_at.desc())
                .limit(30)
            )
        ).all()
        counts: dict[str, int] = {}
        for row in rows:
            if row.pillar:
                counts[row.pillar] = counts.get(row.pillar, 0) + 1
        return counts

    def _choose_pillar(
        self,
        pillars: Sequence[ContentStrategyPillar],
        recent_counts: dict[str, int],
        campaign: ContentCampaign | None,
    ) -> str | None:
        if not pillars:
            return None
        allowed = set(campaign.allowed_pillars) if campaign and campaign.allowed_pillars else None
        candidates = [item for item in pillars if not allowed or item.name in allowed]
        return max(
            candidates, key=lambda item: item.weight / (1 + recent_counts.get(item.name, 0))
        ).name

    @staticmethod
    def _campaign_for_slot(
        campaigns: Sequence[ContentCampaign], slot: datetime
    ) -> ContentCampaign | None:
        active = [
            item
            for item in campaigns
            if (item.starts_at is None or item.starts_at <= slot)
            and (item.ends_at is None or item.ends_at >= slot)
        ]
        return max(active, key=lambda item: item.priority, default=None)
