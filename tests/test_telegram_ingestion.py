from datetime import UTC, datetime

from aiogram.types import Chat, Message, User, Video, Voice

from app.bot.ingestion import build_source_payload
from app.schemas.api import SourceCreate
from app.services.inbox import InboxService


def telegram_message(**kwargs) -> Message:
    return Message(
        message_id=kwargs.pop("message_id", 10),
        date=datetime.now(UTC),
        chat=Chat(id=100, type="private"),
        from_user=User(id=42, is_bot=False, first_name="Owner", username="owner"),
        **kwargs,
    )


def test_voice_creates_source_payload() -> None:
    message = telegram_message(
        voice=Voice(
            file_id="voice-file",
            file_unique_id="voice-unique",
            duration=17,
            mime_type="audio/ogg",
            file_size=1234,
        )
    )

    payload = build_source_payload(message, update_id=900)

    assert payload["type"] == "voice"
    assert payload["telegram_file_id"] == "voice-file"
    assert payload["telegram_unique_file_id"] == "voice-unique"
    assert payload["telegram_update_id"] == 900
    assert payload["duration_seconds"] == 17


def test_video_creates_source_payload() -> None:
    message = telegram_message(
        video=Video(
            file_id="video-file",
            file_unique_id="video-unique",
            width=1080,
            height=1920,
            duration=30,
            file_name="../../unsafe.mp4",
            mime_type="video/mp4",
            file_size=999,
        )
    )

    payload = build_source_payload(message, update_id=901)

    assert payload["type"] == "video"
    assert payload["original_filename"] == "../../unsafe.mp4"
    assert payload["mime_type"] == "video/mp4"


def test_plain_text_and_url_are_detected() -> None:
    text_payload = build_source_payload(telegram_message(text="Обычная заметка"), 1)
    url_payload = build_source_payload(
        telegram_message(text="Посмотри https://example.com/article"), 2
    )

    assert text_payload["type"] == "text"
    assert url_payload["type"] == "url"
    assert url_payload["original_text"] == "https://example.com/article"


async def test_voice_and_video_payloads_create_source_items(session) -> None:
    inbox = InboxService(session)
    messages = [
        telegram_message(
            message_id=20,
            voice=Voice(file_id="v", file_unique_id="vu", duration=2, file_size=10),
        ),
        telegram_message(
            message_id=21,
            video=Video(
                file_id="m",
                file_unique_id="mu",
                width=100,
                height=200,
                duration=3,
                file_size=20,
            ),
        ),
    ]

    created = []
    for update_id, message in enumerate(messages, start=1000):
        source, was_created = await inbox.register_source(
            SourceCreate.model_validate(build_source_payload(message, update_id))
        )
        assert was_created is True
        created.append(source)

    assert created[0].type.value == "voice"
    assert created[1].type.value == "video"
