from sqlalchemy import func, select

from app.ai.mock import MockAIProvider
from app.models import ContentDraft, ContentIdea, SourceItem, User
from app.models.enums import DraftStatus, IdeaStatus, Platform, SourceStatus
from app.schemas.api import SourceCreate
from app.services.content import ContentService


async def test_create_source_creates_user_and_source(session) -> None:
    service = ContentService(session, MockAIProvider())

    source = await service.create_source(
        SourceCreate(
            telegram_user_id=12345,
            telegram_username="owner",
            original_text="Почему приложению не стоит напрямую работать с 1С",
        )
    )

    assert source.processing_status == SourceStatus.NEW
    assert source.original_text is not None
    assert await session.scalar(select(func.count()).select_from(User)) == 1
    assert await session.scalar(select(func.count()).select_from(SourceItem)) == 1


async def test_generation_workflow_and_repurpose(session) -> None:
    service = ContentService(session, MockAIProvider())
    source = await service.create_source(
        SourceCreate(telegram_user_id=42, original_text="Интеграция приложения с 1С")
    )

    ideas = await service.generate_ideas(source.id)
    draft = await service.generate_draft(ideas[0].id)
    repurposed = await service.repurpose(draft.id)

    assert len(ideas) == 3
    assert len({idea.angle for idea in ideas}) == 3
    assert (await service.get_source(source.id)).processing_status == SourceStatus.READY
    assert ideas[0].status == IdeaStatus.SELECTED
    assert draft.status == DraftStatus.DRAFT
    assert draft.platform == Platform.YOUTUBE_SHORTS
    assert len(draft.scene_breakdown) == 3
    assert {item.platform for item in repurposed} == {
        Platform.YOUTUBE_SHORTS,
        Platform.TIKTOK,
        Platform.TELEGRAM,
    }
    assert await session.scalar(select(func.count()).select_from(ContentIdea)) == 3
    assert await session.scalar(select(func.count()).select_from(ContentDraft)) == 4


async def test_regeneration_keeps_previous_version(session) -> None:
    service = ContentService(session, MockAIProvider())
    source = await service.create_source(
        SourceCreate(telegram_user_id=42, original_text="Идея для ролика")
    )
    idea = (await service.generate_ideas(source.id))[0]

    first = await service.generate_draft(idea.id)
    second = await service.generate_draft(idea.id)

    assert first.id != second.id
    assert await session.scalar(select(func.count()).select_from(ContentDraft)) == 2
