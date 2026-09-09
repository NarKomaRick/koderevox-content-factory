import asyncio

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.access import AccessMiddleware
from app.bot.api_client import BackendClient
from app.bot.handlers import router
from app.core.config import get_settings
from app.core.logging import configure_logging


async def run() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    if not settings.telegram_bot_token:
        raise RuntimeError("TELEGRAM_BOT_TOKEN must be configured")
    if not settings.telegram_allowed_user_ids:
        raise RuntimeError("TELEGRAM_ALLOWED_USER_IDS must contain at least one user")
    session = AiohttpSession(proxy=settings.telegram_proxy_url or None)
    bot = Bot(token=settings.telegram_bot_token, session=session)
    backend = BackendClient(settings.backend_url)
    dispatcher = Dispatcher(storage=MemoryStorage())
    access = AccessMiddleware(set(settings.telegram_allowed_user_ids))
    dispatcher.message.outer_middleware(access)
    dispatcher.callback_query.outer_middleware(access)
    dispatcher.include_router(router)
    try:
        await dispatcher.start_polling(bot, backend=backend)
    finally:
        await backend.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run())
