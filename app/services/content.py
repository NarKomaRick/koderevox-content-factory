import time
import uuid
from collections.abc import Sequence

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.base import AIProvider
from app.ai.prompts.idea_generator import build_idea_prompt
from app.ai.prompts.repurpose import build_repurpose_prompt
from app.ai.prompts.short_script import build_short_script_prompt
from app.ai.prompts.system import build_system_prompt
from app.ai.prompts.telegram_post import build_telegram_post_prompt
from app.core.config import get_settings
from app.models import ContentDraft, ContentIdea, Project, SourceItem, SourceNote, User
from app.models.enums import (
    ContentFormat,
    ContentPillar,
    DraftStatus,
    IdeaStatus,
    Platform,
    SourceStatus,
    UserRole,
)
from app.schemas.ai import ContentAngleBatch, RepurposeBundle, RepurposedItem, ShortScript
from app.schemas.api import ProjectCreate, ProjectUpdate, SourceCreate
from app.services.errors import InvalidStateError, NotFoundError

logger = structlog.get_logger()


class ContentService:
    def __init__(self, session: AsyncSession, ai_provider: AIProvider) -> None:
        self.session = session
        self.ai = ai_provider

    async def list_projects(self) -> Sequence[Project]:
        return (await self.session.scalars(select(Project).order_by(Project.name))).all()

    async def create_project(self, data: ProjectCreate) -> Project:
        values = data.model_dump()
        values["timezone"] = data.timezone or get_settings().default_timezone
        project = Project(**values)
        self.session.add(project)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def update_project(self, project_id: uuid.UUID, data: ProjectUpdate) -> Project:
        project = await self._get_project(project_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(project, field, value)
        await self.session.commit()
        await self.session.refresh(project)
        return project

    async def create_source(self, data: SourceCreate) -> SourceItem:
        project = await self._get_project(data.project_id)
        user = await self.session.scalar(
            select(User).where(User.telegram_id == data.telegram_user_id)
        )
        if user is None:
            owner_id = get_settings().initial_owner_telegram_id
            user = User(
                telegram_id=data.telegram_user_id,
                username=data.telegram_username,
                role=UserRole.OWNER if owner_id == data.telegram_user_id else UserRole.ADMIN,
            )
            self.session.add(user)
            await self.session.flush()
        elif get_settings().initial_owner_telegram_id == data.telegram_user_id:
            user.role = UserRole.OWNER
        elif data.telegram_username and user.username != data.telegram_username:
            user.username = data.telegram_username

        source = SourceItem(
            project_id=project.id,
            user_id=user.id,
            type=data.type,
            original_text=data.original_text,
            transcript=data.transcript,
            telegram_file_id=data.telegram_file_id,
            local_file_path=data.local_file_path,
            source_metadata=data.metadata,
            processing_status=SourceStatus.NEW,
        )
        self.session.add(source)
        await self.session.commit()
        await self.session.refresh(source)
        await logger.ainfo(
            "source_created",
            source_id=str(source.id),
            source_type=source.type.value,
            telegram_user_id=data.telegram_user_id,
        )
        return source

    async def list_sources(self) -> Sequence[SourceItem]:
        query = select(SourceItem).order_by(SourceItem.created_at.desc())
        return (await self.session.scalars(query)).all()

    async def get_source(self, source_id: uuid.UUID) -> SourceItem:
        source = await self.session.get(SourceItem, source_id)
        if source is None:
            raise NotFoundError("SourceItem not found")
        return source

    async def generate_ideas(self, source_id: uuid.UUID) -> list[ContentIdea]:
        source = await self.get_source(source_id)
        source_text = await self._build_source_context(source)
        if not source_text:
            raise InvalidStateError("SourceItem has no text or transcript")
        project = await self._get_project(source.project_id)
        source.processing_status = SourceStatus.PROCESSING
        await self.session.commit()
        started = time.monotonic()
        try:
            batch = await self.ai.generate_structured(
                system_prompt=build_system_prompt(project),
                user_prompt=build_idea_prompt(source_text),
                response_model=ContentAngleBatch,
            )
            ideas = [
                ContentIdea(
                    project_id=project.id,
                    source_item_id=source.id,
                    title=angle.title,
                    description=angle.description,
                    angle=angle.angle,
                    suggested_hook=angle.hook,
                    suggested_format=angle.format,
                    estimated_duration=angle.estimated_duration,
                    target_audience=angle.target_audience,
                    content_pillar=angle.content_pillar,
                    score=angle.score,
                    status=IdeaStatus.DRAFT,
                )
                for angle in batch.angles
            ]
            self.session.add_all(ideas)
            source.processing_status = SourceStatus.READY
            await self.session.commit()
            for idea in ideas:
                await self.session.refresh(idea)
            await logger.ainfo(
                "ideas_generated",
                source_id=str(source.id),
                count=len(ideas),
                duration_ms=round((time.monotonic() - started) * 1000),
            )
            return ideas
        except Exception:
            await self.session.rollback()
            failed_source = await self.get_source(source.id)
            failed_source.processing_status = SourceStatus.FAILED
            await self.session.commit()
            await logger.aexception("idea_generation_failed", source_id=str(source.id))
            raise

    async def list_ideas(self) -> Sequence[ContentIdea]:
        query = select(ContentIdea).order_by(ContentIdea.created_at.desc())
        return (await self.session.scalars(query)).all()

    async def get_idea(self, idea_id: uuid.UUID) -> ContentIdea:
        idea = await self.session.get(ContentIdea, idea_id)
        if idea is None:
            raise NotFoundError("ContentIdea not found")
        return idea

    async def generate_draft(self, idea_id: uuid.UUID) -> ContentDraft:
        idea = await self.get_idea(idea_id)
        project = await self._get_project(idea.project_id)
        idea.status = IdeaStatus.SELECTED
        placeholder = ContentDraft(
            idea_id=idea.id,
            platform=Platform.YOUTUBE_SHORTS,
            format=ContentFormat.SHORT_VIDEO,
            title=idea.title,
            hook=idea.suggested_hook,
            script="",
            caption="",
            description="",
            call_to_action="",
            scene_breakdown=[],
            estimated_duration=idea.estimated_duration,
            status=DraftStatus.GENERATING,
            llm_metadata={},
        )
        self.session.add(placeholder)
        await self.session.commit()
        await self.session.refresh(placeholder)
        started = time.monotonic()
        try:
            result = await self.ai.generate_structured(
                system_prompt=build_system_prompt(project),
                user_prompt=build_short_script_prompt(idea),
                response_model=ShortScript,
            )
            placeholder.title = result.title
            placeholder.hook = result.hook
            placeholder.script = result.script
            placeholder.scene_breakdown = [scene.model_dump() for scene in result.scenes]
            placeholder.caption = result.caption
            placeholder.description = result.description
            placeholder.call_to_action = result.call_to_action
            placeholder.estimated_duration = result.estimated_duration
            placeholder.status = DraftStatus.DRAFT
            placeholder.llm_metadata = {
                "schema": "ShortScript",
                "generation_ms": round((time.monotonic() - started) * 1000),
            }
            await self.session.commit()
            await self.session.refresh(placeholder)
            await logger.ainfo(
                "draft_generated",
                idea_id=str(idea.id),
                draft_id=str(placeholder.id),
                duration_ms=placeholder.llm_metadata["generation_ms"],
            )
            return placeholder
        except Exception as exc:
            await self.session.rollback()
            failed_draft = await self.get_draft(placeholder.id)
            failed_draft.status = DraftStatus.REJECTED
            failed_draft.llm_metadata = {"error_type": type(exc).__name__}
            await self.session.commit()
            await logger.aexception("draft_generation_failed", idea_id=str(idea.id))
            raise

    async def list_drafts(self) -> Sequence[ContentDraft]:
        query = select(ContentDraft).order_by(ContentDraft.created_at.desc())
        return (await self.session.scalars(query)).all()

    async def get_draft(self, draft_id: uuid.UUID) -> ContentDraft:
        draft = await self.session.get(ContentDraft, draft_id)
        if draft is None:
            raise NotFoundError("ContentDraft not found")
        return draft

    async def update_draft_status(self, draft_id: uuid.UUID, status: DraftStatus) -> ContentDraft:
        draft = await self.get_draft(draft_id)
        draft.status = status
        await self.session.commit()
        await self.session.refresh(draft)
        return draft

    async def delete_draft(self, draft_id: uuid.UUID) -> None:
        draft = await self.get_draft(draft_id)
        await self.session.delete(draft)
        await self.session.commit()

    async def repurpose(self, draft_id: uuid.UUID) -> list[ContentDraft]:
        source_draft = await self.get_draft(draft_id)
        idea = await self.get_idea(source_draft.idea_id)
        project = await self._get_project(idea.project_id)
        bundle = await self.ai.generate_structured(
            system_prompt=build_system_prompt(project),
            user_prompt=build_repurpose_prompt(idea, source_draft),
            response_model=RepurposeBundle,
        )
        specs = [
            (Platform.YOUTUBE_SHORTS, ContentFormat.SHORT_VIDEO, bundle.youtube_short),
            (Platform.TIKTOK, ContentFormat.SHORT_VIDEO, bundle.tiktok),
            (Platform.TELEGRAM, ContentFormat.POST, bundle.telegram_post),
        ]
        drafts = [
            self._adapted_draft(idea.id, platform, format_, item)
            for platform, format_, item in specs
        ]
        self.session.add_all(drafts)
        await self.session.commit()
        for draft in drafts:
            await self.session.refresh(draft)
        await logger.ainfo(
            "draft_repurposed", source_draft_id=str(source_draft.id), count=len(drafts)
        )
        return drafts

    async def generate_short_from_source(self, source_id: uuid.UUID) -> ContentDraft:
        source = await self.get_source(source_id)
        selected = await self._get_or_create_source_idea(source)
        draft = await self.generate_draft(selected.id)
        source.processing_status = SourceStatus.USED
        await self.session.commit()
        return draft

    async def generate_telegram_post_from_source(self, source_id: uuid.UUID) -> ContentDraft:
        source = await self.get_source(source_id)
        source_text = await self._build_source_context(source)
        if not source_text:
            raise InvalidStateError("SourceItem has no text or transcript")
        idea = await self._get_or_create_source_idea(source)
        project = await self._get_project(source.project_id)
        result = await self.ai.generate_structured(
            system_prompt=build_system_prompt(project),
            user_prompt=build_telegram_post_prompt(idea, source_text),
            response_model=RepurposedItem,
        )
        draft = self._adapted_draft(idea.id, Platform.TELEGRAM, ContentFormat.POST, result)
        self.session.add(draft)
        source.processing_status = SourceStatus.USED
        await self.session.commit()
        await self.session.refresh(draft)
        return draft

    async def _get_or_create_source_idea(self, source: SourceItem) -> ContentIdea:
        existing = list(
            await self.session.scalars(
                select(ContentIdea).where(ContentIdea.source_item_id == source.id)
            )
        )
        if existing:
            return max(existing, key=lambda item: item.score or 0)

        analysis = source.content_analysis or {}
        angles = analysis.get("content_angles") or []
        audiences = analysis.get("target_audiences") or []
        pillars = analysis.get("content_pillars") or []
        try:
            pillar = ContentPillar(pillars[0]) if pillars else ContentPillar.EDUCATION
        except ValueError:
            pillar = ContentPillar.EDUCATION
        title = source.topic or (source.original_text or "Новый материал")[:300]
        summary = source.summary or source.original_text or source.transcript or title
        idea = ContentIdea(
            project_id=source.project_id,
            source_item_id=source.id,
            title=title,
            description=summary,
            angle=str(angles[0]) if angles else summary,
            suggested_hook=title,
            suggested_format=ContentFormat.SHORT_VIDEO,
            estimated_duration=45,
            target_audience=str(audiences[0]) if audiences else "техническая аудитория",
            content_pillar=pillar,
            score=(source.content_potential_score or 70) / 10,
            status=IdeaStatus.SELECTED,
        )
        self.session.add(idea)
        await self.session.commit()
        await self.session.refresh(idea)
        return idea

    def _adapted_draft(
        self,
        idea_id: uuid.UUID,
        platform: Platform,
        format_: ContentFormat,
        item: RepurposedItem,
    ) -> ContentDraft:
        return ContentDraft(
            idea_id=idea_id,
            platform=platform,
            format=format_,
            title=item.title,
            hook=item.hook,
            script=item.script,
            caption=item.caption,
            description=item.description,
            call_to_action=item.call_to_action,
            estimated_duration=item.estimated_duration,
            scene_breakdown=[],
            status=DraftStatus.DRAFT,
            llm_metadata={"schema": "RepurposeBundle"},
        )

    async def _get_project(self, project_id: uuid.UUID | None) -> Project:
        if project_id is not None:
            project = await self.session.get(Project, project_id)
        else:
            query = select(Project).order_by(Project.created_at).limit(1)
            project = await self.session.scalar(query)
        if project is None:
            raise NotFoundError("Project not found")
        return project

    async def _build_source_context(self, source: SourceItem) -> str:
        parts = [
            f"Исходный текст:\n{source.original_text}" if source.original_text else "",
            f"Транскрипция:\n{source.transcript}" if source.transcript else "",
            f"Извлечённый текст:\n{source.extracted_text}" if source.extracted_text else "",
            f"Тема:\n{source.topic}" if source.topic else "",
            f"Summary:\n{source.summary}" if source.summary else "",
        ]
        facts = source.content_analysis.get("source_facts", [])
        key_points = source.content_analysis.get("key_points", [])
        if facts:
            parts.append("Факты из источника:\n- " + "\n- ".join(map(str, facts)))
        if key_points:
            parts.append("Ключевые мысли:\n- " + "\n- ".join(map(str, key_points)))
        notes = await self.session.scalars(
            select(SourceNote)
            .where(SourceNote.source_item_id == source.id)
            .order_by(SourceNote.created_at)
        )
        note_values = [note.text or note.transcript for note in notes]
        if any(note_values):
            parts.append("Уточнения пользователя:\n- " + "\n- ".join(filter(None, note_values)))
        return "\n\n".join(filter(None, parts))
