import re
from typing import Any

from aiogram.types import Message

URL_PATTERN = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)


class UnsupportedTelegramMessage(ValueError):
    pass


def build_source_payload(message: Message, update_id: int | None = None) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "telegram_user_id": message.from_user.id if message.from_user else 0,
        "telegram_username": message.from_user.username if message.from_user else None,
        "telegram_chat_id": message.chat.id,
        "telegram_message_id": message.message_id,
        "telegram_update_id": update_id,
        "metadata": {},
    }
    if message.text:
        urls = URL_PATTERN.findall(message.text)
        if urls:
            payload.update(
                type="url",
                original_text=urls[0].rstrip(".,);]"),
                metadata={"caption": message.text, "urls": urls},
            )
        else:
            payload.update(type="text", original_text=message.text)
        return payload
    media: Any
    if message.voice:
        media = message.voice
        payload.update(type="voice", mime_type=media.mime_type or "audio/ogg")
    elif message.audio:
        media = message.audio
        payload.update(type="audio", mime_type=media.mime_type, original_filename=media.file_name)
    elif message.video:
        media = message.video
        payload.update(type="video", mime_type=media.mime_type, original_filename=media.file_name)
    elif message.video_note:
        media = message.video_note
        payload.update(type="video_note", mime_type="video/mp4")
    elif message.photo:
        media = message.photo[-1]
        payload.update(type="image", mime_type="image/jpeg")
    elif message.document:
        media = message.document
        payload.update(
            type="document", mime_type=media.mime_type, original_filename=media.file_name
        )
    else:
        raise UnsupportedTelegramMessage("Unsupported Telegram message type")
    payload.update(
        telegram_file_id=media.file_id,
        telegram_unique_file_id=media.file_unique_id,
        file_size=getattr(media, "file_size", None),
        duration_seconds=getattr(media, "duration", None),
        original_text=message.caption,
        metadata={"caption": message.caption} if message.caption else {},
    )
    return payload


def received_message(source_type: str) -> str:
    labels = {
        "voice": "🎤 Получил голосовое. Обрабатываю…",
        "audio": "🎵 Получил аудио. Обрабатываю…",
        "video": "🎥 Получил видео. Обрабатываю…",
        "video_note": "🎥 Получил видеосообщение. Обрабатываю…",
        "image": "🖼 Получил изображение. Сохраняю…",
        "document": "📄 Получил документ. Обрабатываю…",
        "url": "🔗 Получил ссылку. Анализирую…",
        "text": "📝 Добавил заметку в Inbox. Анализирую…",
    }
    return labels.get(source_type, "📥 Материал получен. Обрабатываю…")
