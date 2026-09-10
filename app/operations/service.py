from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import (
    ApprovalRequest,
    ContentCampaign,
    ContentItem,
    ContentSeries,
    ContentStrategy,
    ContentStrategyPillar,
    ProducerRun,
    Project,
    User,
)
from app.operations.audit import audit
from app.operations.clock import Clock, SystemClock
from app.operations.domain import (
    ApprovalStatus,
    ContentItemStatus,
    ManualPriority,
    ensure_content_item_transition,
)
from app.operations.policies import OperationsPolicy
from app.operations.schemas import (
    CampaignCreate,
    ContentItemCreate,
    ContentItemPatch,
    SeriesCreate,
    StrategyCreate,
    StrategyPatch,
)
from app.services.errors import InvalidStateError, NotFoundError


class OperationsService:
    def __init__(
        self, session: AsyncSession, settings: Settings | None = None, *, clock: Clock | None = None
    ) -> None:
        self.session = session
        self.settings = settings or Settings()
        self.clock = clock or SystemClock()
        self.policy = OperationsPolicy.from_settings(self.settings)

    @staticmethod
    def transition(item: ContentItem, target: ContentItemStatus) -> None:
        ensure_content_item_transition(item.status, target)
        item.status = target

    async def create_strategy(self, data: StrategyCreate) -> ContentStrategy:
        project = await self.session.get(Project, data.project_id)
        user = await self.session.get(User, data.user_id)
        if project is None or user is None:
            raise NotFoundError("Project or user not found")
        strategy = ContentStrategy(
            project_id=data.project_id,
            user_id=data.user_id,
            channel_profile_id=data.channel_profile_id,
            name=data.name,
            goal=data.goal,
            default_platforms=data.default_platforms,
            default_duration=data.default_duration,
            weekly_target=data.weekly_target,
            approval_policy=data.approval_policy,
            autonomous_mode=data.autonomous_mode,
            auto_publish=data.auto_publish,
            timezone=data.timezone or project.timezone,
            recurrence_rule=data.recurrence_rule,
        )
        self.session.add(strategy)
        await self.session.flush()
        for pillar in data.content_pillars:
            self.session.add(ContentStrategyPillar(strategy_id=strategy.id, **pillar.model_dump()))
        await audit(
            self.session,
            "strategy_created",
            strategy_id=strategy.id,
            project_id=data.project_id,
            rationale="strategy created",
        )
        await self.session.commit()
        await self.session.refresh(strategy)
        return strategy

    async def get_strategy(self, strategy_id: uuid.UUID) -> ContentStrategy:
        item = await self.session.get(ContentStrategy, strategy_id)
        if item is None:
            raise NotFoundError("ContentStrategy not found")
        return item

    async def list_strategies(self, project_id: uuid.UUID | None = None) -> list[ContentStrategy]:
        query = select(ContentStrategy).order_by(ContentStrategy.created_at.desc())
        if project_id:
            query = query.where(ContentStrategy.project_id == project_id)
        return list((await self.session.scalars(query)).all())

    async def update_strategy(self, strategy_id: uuid.UUID, data: StrategyPatch) -> ContentStrategy:
        strategy = await self.get_strategy(strategy_id)
        for key, value in data.model_dump(exclude_unset=True).items():
            setattr(strategy, key, value)
        await self.session.commit()
        await self.session.refresh(strategy)
        return strategy

    async def create_campaign(self, data: CampaignCreate) -> ContentCampaign:
        await self.get_strategy(data.strategy_id)
        campaign = ContentCampaign(**data.model_dump())
        self.session.add(campaign)
        await self.session.commit()
        await self.session.refresh(campaign)
        return campaign

    async def create_series(self, data: SeriesCreate) -> ContentSeries:
        await self.get_strategy(data.strategy_id)
        series = ContentSeries(**data.model_dump())
        self.session.add(series)
        await self.session.commit()
        await self.session.refresh(series)
        return series

    async def create_item(self, data: ContentItemCreate) -> ContentItem:
        strategy = await self.get_strategy(data.strategy_id)
        values = data.model_dump(exclude_unset=True)
        values["strategy_id"] = strategy.id
        values.setdefault("project_id", strategy.project_id)
        values.setdefault("user_id", strategy.user_id)
        values["target_platforms"] = values.get("target_platforms") or strategy.default_platforms
        values["status"] = ContentItemStatus.PLANNED
        values.setdefault("manual_priority", ManualPriority.NORMAL)
        values.setdefault("scheduled_for", self.clock.now())
        values["idempotency_key"] = values.get("idempotency_key") or f"manual:{uuid.uuid4()}"
        item = ContentItem(**values)
        self.session.add(item)
        await self.session.flush()
        await audit(
            self.session,
            "content_planned",
            strategy_id=strategy.id,
            project_id=strategy.project_id,
            content_item_id=item.id,
            rationale="manual content item",
        )
        await self.session.commit()
        await self.session.refresh(item)
        return item

    async def get_item(self, item_id: uuid.UUID) -> ContentItem:
        item = await self.session.get(ContentItem, item_id)
        if item is None:
            raise NotFoundError("ContentItem not found")
        return item

    async def list_items(
        self,
        *,
        strategy_id: uuid.UUID | None = None,
        status: ContentItemStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ContentItem]:
        query = (
            select(ContentItem)
            .order_by(ContentItem.scheduled_for, ContentItem.priority.desc())
            .limit(limit)
            .offset(offset)
        )
        if strategy_id:
            query = query.where(ContentItem.strategy_id == strategy_id)
        if status:
            query = query.where(ContentItem.status == status)
        return list((await self.session.scalars(query)).all())

    async def patch_item(self, item_id: uuid.UUID, data: ContentItemPatch) -> ContentItem:
        item = await self.get_item(item_id)
        allowed = {ContentItemStatus.PLANNED, ContentItemStatus.QUEUED, ContentItemStatus.DEFERRED}
        values = data.model_dump(exclude_unset=True)
        if (
            values
            and item.locked
            and any(key in values for key in {"scheduled_for", "topic_hint", "pillar", "priority"})
        ):
            raise InvalidStateError("ITEM_LOCKED")
        if item.status not in allowed and values:
            raise InvalidStateError("INVALID_TRANSITION")
        for key, value in values.items():
            setattr(item, key, value)
        await self.session.commit()
        return item

    async def cancel_item(self, item_id: uuid.UUID) -> ContentItem:
        item = await self.get_item(item_id)
        if item.status in {ContentItemStatus.PUBLISHED, ContentItemStatus.CANCELLED}:
            return item
        self.transition(item, ContentItemStatus.CANCELLED)
        item.blocked_reason = "cancelled"
        if item.producer_run_id:
            run = await self.session.get(ProducerRun, item.producer_run_id)
            if run and run.status not in {"completed", "cancelled"}:
                run.status = "cancelled"
                run.cancelled_at = self.clock.now()
        await audit(
            self.session,
            "content_cancelled",
            strategy_id=item.strategy_id,
            project_id=item.project_id,
            content_item_id=item.id,
            rationale="operator cancelled item",
        )
        await self.session.commit()
        return item

    async def set_paused(self, item_id: uuid.UUID, paused: bool) -> ContentItem:
        item = await self.get_item(item_id)
        if paused and item.status not in {ContentItemStatus.PUBLISHED, ContentItemStatus.CANCELLED}:
            self.transition(item, ContentItemStatus.PAUSED)
        elif not paused and item.status == ContentItemStatus.PAUSED:
            self.transition(item, ContentItemStatus.QUEUED)
        await self.session.commit()
        return item

    async def retry_item(self, item_id: uuid.UUID) -> ContentItem:
        item = await self.get_item(item_id)
        if item.status not in {
            ContentItemStatus.FAILED,
            ContentItemStatus.MANUAL_REQUIRED,
            ContentItemStatus.DEFERRED,
        }:
            raise InvalidStateError("INVALID_TRANSITION")
        self.transition(item, ContentItemStatus.QUEUED)
        item.blocked_reason = None
        await audit(
            self.session,
            "retry_scheduled",
            strategy_id=item.strategy_id,
            project_id=item.project_id,
            content_item_id=item.id,
            rationale="manual retry",
        )
        await self.session.commit()
        return item

    async def calendar(
        self,
        *,
        start: datetime | None = None,
        end: datetime | None = None,
        strategy_id: uuid.UUID | None = None,
    ) -> list[ContentItem]:
        query = select(ContentItem).order_by(ContentItem.scheduled_for, ContentItem.priority.desc())
        if start:
            query = query.where(ContentItem.scheduled_for >= start)
        if end:
            query = query.where(ContentItem.scheduled_for <= end)
        if strategy_id:
            query = query.where(ContentItem.strategy_id == strategy_id)
        return list((await self.session.scalars(query.limit(500))).all())

    async def approvals(self, status: ApprovalStatus | None = None) -> list[ApprovalRequest]:
        query = select(ApprovalRequest).order_by(ApprovalRequest.requested_at.desc()).limit(100)
        if status:
            query = query.where(ApprovalRequest.status == status)
        return list((await self.session.scalars(query)).all())
