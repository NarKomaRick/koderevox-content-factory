import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Publication, PublicationEvent
from app.models.enums import PublicationEventType, PublicationStatus


class PublicationScheduler:
    """Claims due rows in PostgreSQL; Redis only transports already-claimed IDs."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def claim_due(self, *, now: datetime | None = None, limit: int = 100) -> list[uuid.UUID]:
        current = now or datetime.now(UTC)
        due_condition = or_(
            and_(
                Publication.status == PublicationStatus.SCHEDULED,
                Publication.scheduled_at <= current,
            ),
            and_(
                Publication.status == PublicationStatus.RETRY_WAIT,
                Publication.next_retry_at <= current,
            ),
        )
        rows = (
            await self.session.scalars(
                select(Publication)
                .where(due_condition, Publication.remote_id.is_(None))
                .order_by(Publication.scheduled_at, Publication.next_retry_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        ids: list[uuid.UUID] = []
        for publication in rows:
            publication.status = PublicationStatus.QUEUED
            publication.task_id = None
            self.session.add(
                PublicationEvent(
                    publication_id=publication.id,
                    event_type=PublicationEventType.CLAIMED,
                    details={"by": "scheduler", "due_at": current.isoformat()},
                )
            )
            ids.append(publication.id)
        await self.session.commit()
        return ids

    async def unclaimed_queued(self, *, limit: int = 100) -> list[uuid.UUID]:
        return list(
            await self.session.scalars(
                select(Publication.id)
                .where(
                    Publication.status == PublicationStatus.QUEUED,
                    Publication.task_id.is_(None),
                    Publication.remote_id.is_(None),
                )
                .limit(limit)
            )
        )

    async def due_processing(
        self, *, now: datetime | None = None, limit: int = 100
    ) -> list[uuid.UUID]:
        current = now or datetime.now(UTC)
        rows = (
            await self.session.scalars(
                select(Publication)
                .where(
                    Publication.status == PublicationStatus.PROCESSING,
                    Publication.next_retry_at <= current,
                    Publication.remote_id.is_not(None),
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
        for publication in rows:
            publication.next_retry_at = None
        await self.session.commit()
        return [item.id for item in rows]
