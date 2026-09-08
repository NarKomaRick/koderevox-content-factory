import asyncio
import uuid
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import structlog
from celery import Task  # type: ignore[import-untyped]

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.models import SourceItem, User
from app.services.errors import PermanentProcessingError, TemporaryProcessingError
from app.services.notifier import TelegramNotifier
from app.services.processing_factory import create_processing_service
from app.tasks.celery_app import celery_app

logger = structlog.get_logger()


def run_async[ResultT](coroutine: Coroutine[Any, Any, ResultT]) -> ResultT:
    """Run task async code both in a worker and Celery eager mode inside FastAPI."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)
    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="celery-eager") as executor:
        return executor.submit(asyncio.run, coroutine).result()


async def process_source_once(source_id: uuid.UUID) -> SourceItem:
    settings = get_settings()
    async with SessionFactory() as session:
        service = create_processing_service(session, settings)
        try:
            return await service.process(source_id)
        finally:
            await service.aclose()


async def process_note_once(note_id: uuid.UUID) -> SourceItem:
    settings = get_settings()
    async with SessionFactory() as session:
        service = create_processing_service(session, settings)
        try:
            return await service.process_voice_note(note_id)
        finally:
            await service.aclose()


async def notify_result(source_id: uuid.UUID, success: bool) -> None:
    settings = get_settings()
    async with SessionFactory() as session:
        source = await session.get(SourceItem, source_id)
        if source is None:
            return
        user = await session.get(User, source.user_id)
        if user is None:
            return
        chat_id = source.telegram_chat_id or user.telegram_id
        notifier = TelegramNotifier(settings.telegram_bot_token)
        try:
            if success:
                await notifier.processed(source, chat_id)
            else:
                await notifier.failed(source, chat_id)
        finally:
            await notifier.aclose()


@celery_app.task(bind=True, name="content_factory.process_source", max_retries=3)
def process_source_task(task: Task, source_id: str) -> str:
    parsed_id = uuid.UUID(source_id)
    try:
        run_async(process_source_once(parsed_id))
    except TemporaryProcessingError as exc:
        retries = int(getattr(task.request, "retries", 0))
        if retries < 3:
            countdown = min(60, 2 ** (retries + 1))
            raise task.retry(exc=exc, countdown=countdown) from exc
        run_async(notify_result(parsed_id, False))
        return "failed"
    except PermanentProcessingError:
        run_async(notify_result(parsed_id, False))
        return "failed"
    except Exception:
        run_async(notify_result(parsed_id, False))
        raise
    run_async(notify_result(parsed_id, True))
    return "ready"


@celery_app.task(bind=True, name="content_factory.process_source_note", max_retries=3)
def process_source_note_task(task: Task, note_id: str) -> str:
    parsed_id = uuid.UUID(note_id)
    try:
        source = run_async(process_note_once(parsed_id))
    except TemporaryProcessingError as exc:
        retries = int(getattr(task.request, "retries", 0))
        if retries < 3:
            raise task.retry(exc=exc, countdown=min(60, 2 ** (retries + 1))) from exc
        return "failed"
    except PermanentProcessingError:
        return "failed"
    run_async(notify_result(source.id, True))
    return "ready"
