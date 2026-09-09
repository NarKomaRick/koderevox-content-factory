import asyncio
import threading
import uuid
from collections.abc import Coroutine
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import structlog
from celery import Task  # type: ignore[import-untyped]
from sqlalchemy import select

from app.core.config import get_settings
from app.db.session import SessionFactory
from app.models import ProductionMaterial, ProductionProject, SourceItem, User, VisualAsset
from app.services.errors import PermanentProcessingError, TemporaryProcessingError
from app.services.notifier import TelegramNotifier
from app.services.processing_factory import create_processing_service
from app.services.production_timeline import AutoAssemblyService
from app.services.runtime_settings import SettingsService
from app.services.voiceovers import VoiceoverService
from app.tasks.celery_app import celery_app

logger = structlog.get_logger()
_async_executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="celery-async")
_loop_state = threading.local()


def _run_on_worker_loop[ResultT](coroutine: Coroutine[Any, Any, ResultT]) -> ResultT:
    loop = getattr(_loop_state, "loop", None)
    if loop is None or loop.is_closed():
        loop = asyncio.new_event_loop()
        _loop_state.loop = loop
    return loop.run_until_complete(coroutine)


def run_async[ResultT](coroutine: Coroutine[Any, Any, ResultT]) -> ResultT:
    """Keep one event loop per worker process so asyncpg connections remain loop-local."""
    return _async_executor.submit(_run_on_worker_loop, coroutine).result()


async def process_source_once(source_id: uuid.UUID) -> SourceItem:
    settings = get_settings()
    async with SessionFactory() as session:
        settings = await SettingsService(session, settings).resolved()
        service = create_processing_service(session, settings)
        try:
            source = await service.process(source_id)
            material = await session.scalar(
                select(ProductionMaterial).where(ProductionMaterial.source_item_id == source.id)
            )
            if material:
                asset = await session.scalar(
                    select(VisualAsset).where(VisualAsset.source_item_id == source.id)
                )
                if asset:
                    material.asset_id = asset.id
                    await session.commit()
                if "voiceover" in material.roles:
                    await VoiceoverService(session).create_from_processed_source(
                        material.production_project_id, source.id
                    )
                elif material.user_instruction and asset:
                    production = await session.get(
                        ProductionProject, material.production_project_id
                    )
                    if production and production.active_timeline_revision_id:
                        placement, revision = await AutoAssemblyService(
                            session, settings
                        ).insert_locked(production.id, material.id, material.user_instruction)
                        if placement.status == "ambiguous" and revision is None:
                            notifier = TelegramNotifier(
                                settings.telegram_bot_token, proxy_url=settings.telegram_proxy_url
                            )
                            try:
                                await notifier.placement_candidates(
                                    source.telegram_chat_id or 0,
                                    material.id,
                                    [item.model_dump() for item in placement.candidates],
                                )
                            finally:
                                await notifier.aclose()
            return source
        finally:
            await service.aclose()


async def process_note_once(note_id: uuid.UUID) -> SourceItem:
    settings = get_settings()
    async with SessionFactory() as session:
        settings = await SettingsService(session, settings).resolved()
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
        notifier = TelegramNotifier(
            settings.telegram_bot_token, proxy_url=settings.telegram_proxy_url
        )
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
