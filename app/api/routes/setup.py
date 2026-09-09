from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.session import get_session
from app.models import User
from app.models.enums import UserRole
from app.schemas.production import AISetupRequest, RuntimeSettingUpdate, SecretUpdate
from app.services.errors import NotFoundError
from app.services.runtime_settings import (
    AIConnectionTester,
    DiagnosticsService,
    EncryptedDatabaseSecretStore,
    SensitiveActionLimiter,
    SettingsService,
)

router = APIRouter(prefix="/setup", tags=["setup"])
SessionDep = Annotated[AsyncSession, Depends(get_session)]
limiter = SensitiveActionLimiter()


async def _owner(session: AsyncSession, telegram_id: int, private_chat: bool) -> User:
    user = await session.scalar(select(User).where(User.telegram_id == telegram_id))
    if user is None and get_settings().initial_owner_telegram_id == telegram_id:
        user = User(telegram_id=telegram_id, username=None, role=UserRole.OWNER)
        session.add(user)
        await session.commit()
        await session.refresh(user)
    if user is None:
        raise NotFoundError("User not found")
    SettingsService.require_owner(user, private_chat=private_chat)
    return user


@router.get("/summary")
async def summary(
    telegram_user_id: int,
    session: SessionDep,
    private_chat: bool = True,
) -> dict[str, Any]:
    await _owner(session, telegram_user_id, private_chat)
    return await SettingsService(session, get_settings()).safe_summary()


@router.get("/diagnostics")
async def diagnostics(
    telegram_user_id: int,
    session: SessionDep,
    private_chat: bool = True,
) -> dict[str, str]:
    await _owner(session, telegram_user_id, private_chat)
    return await DiagnosticsService(session, get_settings()).run()


@router.patch("/runtime-setting")
async def update_runtime_setting(
    data: RuntimeSettingUpdate,
    session: SessionDep,
) -> dict[str, object]:
    owner = await _owner(session, data.telegram_user_id, data.private_chat)
    item = await SettingsService(session, get_settings()).set(data.key, data.value, actor=owner)
    return {"key": item.key, "configured": True}


@router.post("/secret")
async def store_secret(
    data: SecretUpdate,
    session: SessionDep,
) -> dict[str, object]:
    owner = await _owner(session, data.telegram_user_id, data.private_chat)
    settings = get_settings()
    limiter.check(data.telegram_user_id, settings.setup_sensitive_rate_limit_seconds)
    key = settings.app_master_key or settings.credential_encryption_key
    await EncryptedDatabaseSecretStore(session, key).set(owner.id, data.name, data.value)
    return {"name": data.name, "configured": True}


@router.post("/ai/test-and-activate")
async def test_and_activate_ai(
    data: AISetupRequest,
    session: SessionDep,
) -> dict[str, Any]:
    owner = await _owner(session, data.telegram_user_id, data.private_chat)
    limiter.check(data.telegram_user_id, get_settings().setup_sensitive_rate_limit_seconds)
    tester = AIConnectionTester()
    try:
        result = await tester.test(data.base_url, data.model, data.api_key)
    finally:
        await tester.aclose()
    service = SettingsService(session, get_settings())
    await service.set("ai_provider", data.provider, actor=owner)
    await service.set("ai_base_url", data.base_url, actor=owner)
    await service.set("ai_model", data.model, actor=owner)
    if data.api_key:
        settings = get_settings()
        key = settings.app_master_key or settings.credential_encryption_key
        await EncryptedDatabaseSecretStore(session, key).set(owner.id, "ai_api_key", data.api_key)
    return result
