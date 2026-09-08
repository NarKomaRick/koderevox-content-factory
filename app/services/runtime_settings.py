import asyncio
import shutil
import time
import uuid
from typing import Any, Protocol

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import EncryptedSecret, RuntimeSetting, User
from app.models.enums import UserRole
from app.services.errors import InvalidStateError, NotFoundError


class SecretStore(Protocol):
    async def set(self, owner_user_id: uuid.UUID, name: str, value: str) -> None: ...

    async def get(self, owner_user_id: uuid.UUID, name: str) -> str | None: ...

    async def delete(self, owner_user_id: uuid.UUID, name: str) -> None: ...


class EncryptedDatabaseSecretStore:
    """Fernet authenticated encryption; the master key never enters the database."""

    def __init__(self, session: AsyncSession, master_key: str) -> None:
        self.session = session
        self.fernet = Fernet(master_key.encode()) if master_key else None

    async def set(self, owner_user_id: uuid.UUID, name: str, value: str) -> None:
        if self.fernet is None:
            raise InvalidStateError("APP_MASTER_KEY is not configured")
        if await self.session.get(User, owner_user_id) is None:
            raise NotFoundError("User not found")
        encrypted = self.fernet.encrypt(value.encode())
        item = await self.session.scalar(
            select(EncryptedSecret).where(
                EncryptedSecret.owner_user_id == owner_user_id,
                EncryptedSecret.name == name,
            )
        )
        if item is None:
            item = EncryptedSecret(owner_user_id=owner_user_id, name=name, ciphertext=encrypted)
            self.session.add(item)
        else:
            item.ciphertext = encrypted
        await self.session.commit()

    async def get(self, owner_user_id: uuid.UUID, name: str) -> str | None:
        item = await self.session.scalar(
            select(EncryptedSecret).where(
                EncryptedSecret.owner_user_id == owner_user_id,
                EncryptedSecret.name == name,
            )
        )
        if item is None:
            return None
        if self.fernet is None:
            raise InvalidStateError("APP_MASTER_KEY is not configured")
        try:
            return self.fernet.decrypt(item.ciphertext).decode()
        except (InvalidToken, UnicodeDecodeError) as exc:
            raise InvalidStateError("Stored secret cannot be decrypted") from exc

    async def delete(self, owner_user_id: uuid.UUID, name: str) -> None:
        item = await self.session.scalar(
            select(EncryptedSecret).where(
                EncryptedSecret.owner_user_id == owner_user_id,
                EncryptedSecret.name == name,
            )
        )
        if item:
            await self.session.delete(item)
            await self.session.commit()


class SettingsService:
    def __init__(self, session: AsyncSession, environment: Settings) -> None:
        self.session = session
        self.environment = environment

    async def get(
        self,
        key: str,
        *,
        scope: str = "system",
        scope_id: uuid.UUID | None = None,
        default: Any = None,
    ) -> Any:
        item = await self.session.scalar(
            select(RuntimeSetting).where(
                RuntimeSetting.scope == scope,
                RuntimeSetting.scope_id == scope_id,
                RuntimeSetting.key == key,
            )
        )
        if item is not None:
            return item.value
        if hasattr(self.environment, key):
            return getattr(self.environment, key)
        return default

    async def set(
        self,
        key: str,
        value: Any,
        *,
        actor: User,
        scope: str = "system",
        scope_id: uuid.UUID | None = None,
    ) -> RuntimeSetting:
        self.require_owner(actor)
        item = await self.session.scalar(
            select(RuntimeSetting).where(
                RuntimeSetting.scope == scope,
                RuntimeSetting.scope_id == scope_id,
                RuntimeSetting.key == key,
            )
        )
        if item is None:
            item = RuntimeSetting(
                scope=scope,
                scope_id=scope_id,
                key=key,
                value=value,
                updated_by_user_id=actor.id,
            )
            self.session.add(item)
        else:
            item.value = value
            item.updated_by_user_id = actor.id
        await self.session.commit()
        await self.session.refresh(item)
        return item

    @staticmethod
    def require_owner(user: User, *, private_chat: bool = True) -> None:
        if user.role != UserRole.OWNER:
            raise InvalidStateError("Setup is available to OWNER only")
        if not private_chat:
            raise InvalidStateError("Setup is available in private chats only")

    async def safe_summary(self) -> dict[str, Any]:
        return {
            "ai_provider": await self.get("ai_provider"),
            "ai_model": await self.get("ai_model"),
            "ai": "configured" if await self.get("ai_base_url") else "not configured",
            "stt": {
                "provider": await self.get("stt_provider"),
                "model": await self.get("stt_model"),
                "device": await self.get("stt_device"),
                "compute": await self.get("stt_compute_type"),
            },
            "render": f"{await self.get('video_width')}x{await self.get('video_height')}",
            "storage": "local",
        }

    async def resolved(self) -> Settings:
        rows = (
            await self.session.scalars(
                select(RuntimeSetting).where(RuntimeSetting.scope == "system")
            )
        ).all()
        update = {
            item.key: item.value
            for item in rows
            if item.scope_id is None and hasattr(self.environment, item.key)
        }
        resolved = self.environment.model_copy(update=update)
        owner = await self.session.scalar(
            select(User).where(User.role == UserRole.OWNER).order_by(User.created_at)
        )
        key = resolved.app_master_key or resolved.credential_encryption_key
        if owner and key:
            api_key = await EncryptedDatabaseSecretStore(self.session, key).get(
                owner.id, "ai_api_key"
            )
            if api_key is not None:
                resolved.ai_api_key = api_key
        return resolved


class AIConnectionTester:
    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=15)

    async def test(self, base_url: str, model: str, api_key: str | None = None) -> dict[str, Any]:
        started = time.monotonic()
        headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        response = await self.client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers=headers,
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Reply with OK"}],
                "max_tokens": 4,
            },
        )
        response.raise_for_status()
        body = response.json()
        if not body.get("choices"):
            raise InvalidStateError("AI provider response has no choices")
        return {
            "ok": True,
            "model": model,
            "latency_ms": round((time.monotonic() - started) * 1000),
        }

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()


class SensitiveActionLimiter:
    def __init__(self) -> None:
        self._last_action: dict[int, float] = {}

    def check(self, telegram_user_id: int, minimum_interval: int) -> None:
        now = time.monotonic()
        previous = self._last_action.get(telegram_user_id)
        if previous is not None and now - previous < minimum_interval:
            raise InvalidStateError("Sensitive setup action is rate-limited; retry shortly")
        self._last_action[telegram_user_id] = now


class DiagnosticsService:
    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings

    async def run(self) -> dict[str, str]:
        checks = {
            "PostgreSQL": "✅",
            "Redis": "⚪",
            "FFmpeg": "✅" if shutil.which("ffmpeg") and shutil.which("ffprobe") else "❌",
            "Whisper": "✅" if self.settings.stt_provider == "faster_whisper" else "⚪",
            "AI": "✅" if self.settings.ai_provider else "⚪",
            "Telegram": "✅" if self.settings.telegram_bot_token else "⚪",
            "Media worker": "⚪",
            "Render worker": "⚪",
            "Storage": "✅",
            "YouTube": "⚪",
            "TikTok": "⚪",
        }
        try:
            await self.session.execute(text("SELECT 1"))
        except Exception:
            checks["PostgreSQL"] = "❌"
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self.settings.redis_url.split("//")[-1].split(":")[0],
                    int(self.settings.redis_url.rsplit(":", 1)[-1].split("/")[0]),
                ),
                timeout=0.2,
            )
            writer.close()
            await writer.wait_closed()
            del reader
            checks["Redis"] = "✅"
        except Exception:
            pass
        return checks
