import math
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models import ContentIdea, Project, SourceItem, SourceNote, User
from app.models.enums import ProcessingStage, SourceStatus, SourceType, UserRole
from app.schemas.api import DailyDigest, InboxPage, SourceCreate, SourceNoteCreate
from app.services.errors import NotFoundError

logger = structlog.get_logger()


class InboxService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def register_source(self, data: SourceCreate) -> tuple[SourceItem, bool]:
        existing = await self._find_duplicate(data)
        if existing is not None:
            return existing, False
        project = await self._get_project(data.project_id)
        user = await self._get_or_create_user(data.telegram_user_id, data.telegram_username)
        source = SourceItem(
            project_id=project.id,
            user_id=user.id,
            type=data.type,
            original_text=data.original_text,
            transcript=data.transcript,
            telegram_file_id=data.telegram_file_id,
            telegram_unique_file_id=data.telegram_unique_file_id,
            telegram_chat_id=data.telegram_chat_id,
            telegram_message_id=data.telegram_message_id,
            telegram_update_id=data.telegram_update_id,
            local_file_path=data.local_file_path,
            mime_type=data.mime_type,
            file_size=data.file_size,
            original_filename=data.original_filename,
            duration_seconds=data.duration_seconds,
            source_metadata=data.metadata,
            processing_status=SourceStatus.NEW,
            processing_stage=ProcessingStage.RECEIVED,
        )
        self.session.add(source)
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            existing = await self._find_duplicate(data)
            if existing is None:
                raise
            return existing, False
        await self.session.refresh(source)
        await logger.ainfo(
            "inbox_source_registered",
            source_id=str(source.id),
            telegram_update_id=data.telegram_update_id,
            source_type=source.type.value,
        )
        return source, True

    async def get_source(self, source_id: uuid.UUID) -> SourceItem:
        source = await self.session.get(SourceItem, source_id)
        if source is None:
            raise NotFoundError("SourceItem not found")
        return source

    async def list_inbox(
        self,
        *,
        telegram_user_id: int,
        page: int = 1,
        page_size: int = 5,
        source_type: SourceType | None = None,
        status: SourceStatus | None = None,
        best: bool = False,
        query_text: str | None = None,
    ) -> InboxPage:
        filters = [User.telegram_id == telegram_user_id]
        if source_type:
            if source_type == SourceType.VOICE:
                filters.append(SourceItem.type.in_([SourceType.VOICE, SourceType.AUDIO]))
            elif source_type == SourceType.VIDEO:
                filters.append(SourceItem.type.in_([SourceType.VIDEO, SourceType.VIDEO_NOTE]))
            else:
                filters.append(SourceItem.type == source_type)
        if status:
            filters.append(SourceItem.processing_status == status)
        else:
            filters.append(SourceItem.processing_status != SourceStatus.ARCHIVED)
        if query_text:
            term = f"%{query_text.strip()}%"
            filters.append(
                or_(
                    SourceItem.topic.ilike(term),
                    SourceItem.summary.ilike(term),
                    SourceItem.transcript.ilike(term),
                    SourceItem.original_text.ilike(term),
                    SourceItem.extracted_text.ilike(term),
                )
            )
        base = select(SourceItem).join(User).where(*filters)
        count_query = select(func.count()).select_from(SourceItem).join(User).where(*filters)
        total = int(await self.session.scalar(count_query) or 0)
        if best:
            base = base.order_by(
                func.coalesce(SourceItem.content_potential_score, -1).desc(),
                SourceItem.created_at.desc(),
            )
        else:
            base = base.order_by(SourceItem.created_at.desc())
        items = (
            await self.session.scalars(base.offset((page - 1) * page_size).limit(page_size))
        ).all()
        return InboxPage(
            items=list(items),
            total=total,
            page=page,
            page_size=page_size,
            pages=math.ceil(total / page_size) if total else 0,
        )

    async def add_note(self, source_id: uuid.UUID, data: SourceNoteCreate) -> SourceNote:
        source = await self.get_source(source_id)
        if data.telegram_update_id is not None:
            duplicate = await self.session.scalar(
                select(SourceNote).where(SourceNote.telegram_update_id == data.telegram_update_id)
            )
            if duplicate is not None:
                return duplicate
        user = await self._get_or_create_user(data.telegram_user_id, None)
        note = SourceNote(
            source_item_id=source.id,
            user_id=user.id,
            text=data.text,
            telegram_file_id=data.telegram_file_id,
            telegram_unique_file_id=data.telegram_unique_file_id,
            telegram_update_id=data.telegram_update_id,
            mime_type=data.mime_type,
            file_size=data.file_size,
        )
        self.session.add(note)
        source.processing_status = SourceStatus.NEW
        source.processing_stage = ProcessingStage.RECEIVED
        source.processing_error = None
        await self.session.commit()
        await self.session.refresh(note)
        return note

    async def list_notes(self, source_id: uuid.UUID) -> list[SourceNote]:
        await self.get_source(source_id)
        query = (
            select(SourceNote)
            .where(SourceNote.source_item_id == source_id)
            .order_by(SourceNote.created_at)
        )
        return list((await self.session.scalars(query)).all())

    async def archive(self, source_id: uuid.UUID) -> SourceItem:
        source = await self.get_source(source_id)
        source.processing_status = SourceStatus.ARCHIVED
        await self.session.commit()
        await self.session.refresh(source)
        return source

    async def retry(self, source_id: uuid.UUID) -> SourceItem:
        source = await self.get_source(source_id)
        source.processing_status = SourceStatus.NEW
        source.processing_stage = ProcessingStage.RECEIVED
        source.processing_error = None
        await self.session.commit()
        return source

    async def delete(self, source_id: uuid.UUID) -> None:
        source = await self.get_source(source_id)
        await self.session.execute(
            update(ContentIdea)
            .where(ContentIdea.source_item_id == source_id)
            .values(source_item_id=None)
        )
        await self.session.delete(source)
        await self.session.commit()

    async def digest(
        self, telegram_user_id: int, timezone_name: str = "Europe/Moscow"
    ) -> DailyDigest:
        timezone = ZoneInfo(timezone_name)
        local_now = datetime.now(timezone)
        local_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
        start = local_start.astimezone(UTC)
        end = (local_start + timedelta(days=1)).astimezone(UTC)
        query = (
            select(SourceItem)
            .join(User)
            .where(
                User.telegram_id == telegram_user_id,
                SourceItem.created_at >= start,
                SourceItem.created_at < end,
                SourceItem.processing_status != SourceStatus.ARCHIVED,
            )
            .order_by(func.coalesce(SourceItem.content_potential_score, -1).desc())
        )
        items = list((await self.session.scalars(query)).all())
        counts: dict[str, int] = {}
        for item in items:
            for format_name in item.content_analysis.get("recommended_formats", []):
                counts[str(format_name)] = counts.get(str(format_name), 0) + 1
        return DailyDigest(total=len(items), best=items[:3], recommended_format_counts=counts)

    async def _find_duplicate(self, data: SourceCreate) -> SourceItem | None:
        if data.telegram_update_id is not None:
            duplicate = await self.session.scalar(
                select(SourceItem).where(SourceItem.telegram_update_id == data.telegram_update_id)
            )
            if duplicate is not None:
                return duplicate
        if data.telegram_chat_id is not None and data.telegram_message_id is not None:
            return await self.session.scalar(
                select(SourceItem).where(
                    SourceItem.telegram_chat_id == data.telegram_chat_id,
                    SourceItem.telegram_message_id == data.telegram_message_id,
                )
            )
        return None

    async def _get_or_create_user(self, telegram_id: int, username: str | None) -> User:
        user = await self.session.scalar(select(User).where(User.telegram_id == telegram_id))
        owner_id = get_settings().initial_owner_telegram_id
        if user is None:
            role = UserRole.OWNER if owner_id == telegram_id else UserRole.ADMIN
            user = User(telegram_id=telegram_id, username=username, role=role)
            self.session.add(user)
            await self.session.flush()
        elif owner_id == telegram_id and user.role != UserRole.OWNER:
            user.role = UserRole.OWNER
        elif username and user.username != username:
            user.username = username
        return user

    async def _get_project(self, project_id: uuid.UUID | None) -> Project:
        if project_id:
            project = await self.session.get(Project, project_id)
        else:
            query = select(Project).order_by(Project.created_at).limit(1)
            project = await self.session.scalar(query)
        if project is None:
            raise NotFoundError("Project not found")
        return project
