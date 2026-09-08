from app.ai.mock import MockAIProvider
from app.models.enums import SourceStatus, SourceType
from app.schemas.api import SourceCreate, SourceNoteCreate
from app.services.content import ContentService
from app.services.inbox import InboxService


async def test_duplicate_telegram_update_does_not_create_source(session) -> None:
    inbox = InboxService(session)
    data = SourceCreate(
        telegram_user_id=42,
        telegram_chat_id=42,
        telegram_message_id=100,
        telegram_update_id=500,
        type=SourceType.TEXT,
        original_text="Заметка",
    )

    first, first_created = await inbox.register_source(data)
    second, second_created = await inbox.register_source(data)

    assert first_created is True
    assert second_created is False
    assert first.id == second.id


async def test_inbox_pagination_filters_search_and_archive(session) -> None:
    inbox = InboxService(session)
    for index in range(7):
        source, _ = await inbox.register_source(
            SourceCreate(
                telegram_user_id=42,
                telegram_update_id=600 + index,
                type=SourceType.VOICE if index % 2 else SourceType.TEXT,
                original_text=f"REST заметка {index}",
            )
        )
        source.topic = f"REST topic {index}"
        source.summary = f"Summary {index}"
        source.content_potential_score = index * 10
        source.processing_status = SourceStatus.READY
    await session.commit()

    first_page = await inbox.list_inbox(telegram_user_id=42, page=1, page_size=3)
    voice_page = await inbox.list_inbox(
        telegram_user_id=42, source_type=SourceType.VOICE, page_size=10
    )
    best_page = await inbox.list_inbox(telegram_user_id=42, best=True, page_size=2)
    search_page = await inbox.list_inbox(telegram_user_id=42, query_text="topic 4", page_size=10)

    assert first_page.total == 7
    assert first_page.pages == 3
    assert voice_page.total == 3
    assert best_page.items[0].content_potential_score == 60
    assert search_page.total == 1

    await inbox.archive(search_page.items[0].id)
    after_archive = await inbox.list_inbox(telegram_user_id=42, query_text="topic 4")
    assert after_archive.total == 0


async def test_content_service_uses_intelligence_and_notes(session) -> None:
    inbox = InboxService(session)
    source, _ = await inbox.register_source(
        SourceCreate(
            telegram_user_id=42,
            original_text="Мы нашли двойной запрос",
            telegram_update_id=700,
        )
    )
    source.summary = "Запрос повторялся при возврате на экран"
    source.content_analysis = {
        "source_facts": ["1С получала две записи"],
        "key_points": ["Нужна идемпотентность"],
    }
    await session.commit()
    await inbox.add_note(
        source.id,
        SourceNoteCreate(telegram_user_id=42, text="Причина была в lifecycle экрана"),
    )

    service = ContentService(session, MockAIProvider())
    context = await service._build_source_context(source)

    assert "1С получала две записи" in context
    assert "Причина была в lifecycle экрана" in context


async def test_daily_digest_aggregates_recommended_formats(session) -> None:
    inbox = InboxService(session)
    source, _ = await inbox.register_source(
        SourceCreate(telegram_user_id=77, original_text="Сегодняшняя заметка")
    )
    source.topic = "Идемпотентность REST API"
    source.content_potential_score = 82
    source.content_analysis = {"recommended_formats": ["short_video", "telegram_post"]}
    source.processing_status = SourceStatus.READY
    await session.commit()

    digest = await inbox.digest(77)

    assert digest.total == 1
    assert digest.best[0].topic == "Идемпотентность REST API"
    assert digest.recommended_format_counts == {"short_video": 1, "telegram_post": 1}
