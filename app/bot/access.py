from collections.abc import Awaitable, Callable
from typing import Any

import structlog
from aiogram import BaseMiddleware
from aiogram.types import CallbackQuery, Message, TelegramObject

logger = structlog.get_logger()


def is_user_allowed(user_id: int, allowed_user_ids: set[int]) -> bool:
    return user_id in allowed_user_ids


class AccessMiddleware(BaseMiddleware):
    def __init__(self, allowed_user_ids: set[int]) -> None:
        self.allowed_user_ids = allowed_user_ids

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user = data.get("event_from_user")
        if user is not None and is_user_allowed(user.id, self.allowed_user_ids):
            return await handler(event, data)
        await logger.awarning("telegram_access_denied", telegram_user_id=getattr(user, "id", None))
        if isinstance(event, Message):
            await event.answer("Access denied")
        elif isinstance(event, CallbackQuery):
            await event.answer("Access denied", show_alert=True)
        return None
