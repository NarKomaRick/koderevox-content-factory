import uuid

import httpx
import structlog

from app.models import SourceItem
from app.models.enums import SourceType

logger = structlog.get_logger()


class TelegramNotifier:
    def __init__(self, bot_token: str, client: httpx.AsyncClient | None = None) -> None:
        self.bot_token = bot_token
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=30)

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def processed(self, source: SourceItem, chat_id: int) -> None:
        if source.type == SourceType.IMAGE and not source.content_analysis:
            text = "🖼 Изображение сохранено."
            keyboard = [[self._button("✍️ Добавить комментарий", "source_note", source.id)]]
        else:
            formats = source.content_analysis.get("recommended_formats", [])
            format_text = ", ".join(map(str, formats)) or "—"
            score = (
                str(source.content_potential_score)
                if source.content_potential_score is not None
                else "—"
            )
            text = (
                "✅ Материал обработан\n\n"
                f"Тема:\n{source.topic or '—'}\n\n"
                f"Суть:\n{source.summary or '—'}\n\n"
                f"Потенциал: {score}/100\n"
                f"Можно сделать: {format_text}"
            )
            keyboard = [
                [
                    self._button("🎬 Short", "source_short", source.id),
                    self._button("💡 Варианты идей", "source_ideas", source.id),
                ],
                [
                    self._button("📝 Telegram-пост", "source_post", source.id),
                    self._button("📥 Оставить в Inbox", "source_keep", source.id),
                ],
            ]
            if source.content_analysis.get("requires_more_context"):
                questions = source.content_analysis.get("questions_to_user", [])[:3]
                text += "\n\nДля сильного материала не хватает деталей:\n" + "\n".join(
                    f"{index}. {question}" for index, question in enumerate(questions, start=1)
                )
                keyboard = [
                    [
                        self._button("✍️ Ответить текстом", "source_note", source.id),
                        self._button("🎤 Ответить голосом", "source_voice_note", source.id),
                    ],
                    [self._button("➡️ Сделать без уточнений", "source_short", source.id)],
                    *keyboard,
                ]
        await self._send(chat_id, text, keyboard)

    async def failed(self, source: SourceItem, chat_id: int) -> None:
        text = "⚠️ Не удалось обработать материал. Исходный файл сохранён, если он был загружен."
        keyboard = [
            [self._button("🔄 Повторить", "source_retry", source.id)],
            [self._button("📥 Оставить без обработки", "source_keep", source.id)],
            [self._button("🗑 Удалить", "source_delete", source.id)],
        ]
        await self._send(chat_id, text, keyboard)

    async def placement_candidates(
        self,
        chat_id: int,
        material_id: uuid.UUID,
        candidates: list[dict[str, object]],
    ) -> None:
        text = "🎯 Нашёл несколько подходящих мест. Выберите диапазон:"
        keyboard = [
            [
                {
                    "text": (
                        f"{index + 1}. {self._number(item.get('start')):.1f}–"
                        f"{self._number(item.get('end')):.1f} · {str(item['text'])[:24]}"
                    ),
                    "callback_data": f"prod_place:{material_id}:{index}",
                }
            ]
            for index, item in enumerate(candidates[:3])
        ]
        await self._send(chat_id, text, keyboard)

    @staticmethod
    def _number(value: object) -> float:
        return float(value) if isinstance(value, (int, float, str)) else 0.0

    async def _send(self, chat_id: int, text: str, keyboard: list[list[dict[str, str]]]) -> None:
        if not self.bot_token:
            return
        try:
            response = await self.client.post(
                f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
                json={
                    "chat_id": chat_id,
                    "text": text,
                    "reply_markup": {"inline_keyboard": keyboard},
                },
            )
            response.raise_for_status()
        except httpx.HTTPError:
            await logger.aexception("telegram_notification_failed", chat_id=chat_id)

    @staticmethod
    def _button(label: str, action: str, source_id: uuid.UUID) -> dict[str, str]:
        return {"text": label, "callback_data": f"{action}:{source_id}"}
