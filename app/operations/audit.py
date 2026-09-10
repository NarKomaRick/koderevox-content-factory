from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import OperationsAuditEvent


async def audit(
    session: AsyncSession,
    event_type: str,
    *,
    strategy_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    content_item_id: uuid.UUID | None = None,
    rationale: str = "",
    data: dict[str, Any] | None = None,
) -> OperationsAuditEvent:
    event = OperationsAuditEvent(
        event_type=event_type,
        strategy_id=strategy_id,
        project_id=project_id,
        content_item_id=content_item_id,
        rationale=rationale[:2000],
        data=data or {},
    )
    session.add(event)
    await session.flush()
    return event
