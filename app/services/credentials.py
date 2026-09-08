import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

import httpx
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import EncryptedCredential, PlatformAccount
from app.models.enums import PublishingPlatform
from app.services.publishing_errors import AuthenticationError, ProviderTemporaryError


class CredentialProvider(Protocol):
    async def get(self, platform_account_id: uuid.UUID) -> dict[str, Any]: ...

    async def set(
        self,
        platform_account_id: uuid.UUID,
        payload: dict[str, Any],
        *,
        expires_at: datetime | None = None,
    ) -> None: ...

    async def delete(self, platform_account_id: uuid.UUID) -> None: ...


class EncryptedCredentialProvider:
    """Fernet provides authenticated encryption; plaintext tokens never enter SQL columns."""

    def __init__(self, session: AsyncSession, encryption_key: str) -> None:
        self.session = session
        self._fernet = Fernet(encryption_key.encode()) if encryption_key else None

    async def get(self, platform_account_id: uuid.UUID) -> dict[str, Any]:
        credential = await self.session.scalar(
            select(EncryptedCredential).where(
                EncryptedCredential.platform_account_id == platform_account_id
            )
        )
        if credential is None:
            return {}
        if self._fernet is None:
            raise AuthenticationError("Credential encryption key is not configured")
        try:
            plaintext = self._fernet.decrypt(credential.encrypted_payload)
            return dict(json.loads(plaintext))
        except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise AuthenticationError("Stored credentials cannot be decrypted") from exc

    async def set(
        self,
        platform_account_id: uuid.UUID,
        payload: dict[str, Any],
        *,
        expires_at: datetime | None = None,
    ) -> None:
        if self._fernet is None:
            raise AuthenticationError("CREDENTIAL_ENCRYPTION_KEY is not configured")
        if await self.session.get(PlatformAccount, platform_account_id) is None:
            raise AuthenticationError("Platform account does not exist")
        encrypted = self._fernet.encrypt(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        )
        credential = await self.session.scalar(
            select(EncryptedCredential).where(
                EncryptedCredential.platform_account_id == platform_account_id
            )
        )
        if credential is None:
            credential = EncryptedCredential(
                platform_account_id=platform_account_id,
                encrypted_payload=encrypted,
                expires_at=expires_at,
            )
            self.session.add(credential)
        else:
            credential.encrypted_payload = encrypted
            credential.expires_at = expires_at
        await self.session.commit()

    async def delete(self, platform_account_id: uuid.UUID) -> None:
        credential = await self.session.scalar(
            select(EncryptedCredential).where(
                EncryptedCredential.platform_account_id == platform_account_id
            )
        )
        if credential is not None:
            await self.session.delete(credential)
            await self.session.commit()


class TokenManager:
    def __init__(
        self,
        session: AsyncSession,
        provider: CredentialProvider,
        settings: Settings,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.session = session
        self.provider = provider
        self.settings = settings
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=30)

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def get(self, platform_account_id: uuid.UUID) -> dict[str, Any]:
        account = await self.session.get(PlatformAccount, platform_account_id)
        if account is None:
            raise AuthenticationError("Platform account does not exist")
        credentials = await self.provider.get(platform_account_id)
        if not credentials:
            return {}
        expiry = self._expiry(credentials)
        if expiry is None or expiry > datetime.now(UTC) + timedelta(seconds=60):
            return credentials
        refresh_token = credentials.get("refresh_token")
        if not refresh_token:
            raise AuthenticationError("Refresh token is missing")
        refreshed = await self._refresh(account.platform, str(refresh_token))
        merged = {**credentials, **refreshed}
        if not merged.get("refresh_token"):
            merged["refresh_token"] = refresh_token
        await self.provider.set(platform_account_id, merged, expires_at=self._expiry(merged))
        return merged

    async def exchange_code(
        self, account: PlatformAccount, code: str, *, code_verifier: str | None = None
    ) -> dict[str, Any]:
        if account.platform == PublishingPlatform.YOUTUBE:
            data = {
                "client_id": self.settings.youtube_client_id,
                "client_secret": self.settings.youtube_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self.settings.youtube_redirect_uri,
            }
            endpoint = "https://oauth2.googleapis.com/token"
        elif account.platform == PublishingPlatform.TIKTOK:
            data = {
                "client_key": self.settings.tiktok_client_key,
                "client_secret": self.settings.tiktok_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self.settings.tiktok_redirect_uri,
            }
            if code_verifier:
                data["code_verifier"] = code_verifier
            endpoint = "https://open.tiktokapis.com/v2/oauth/token/"
        else:
            raise AuthenticationError("This platform does not use OAuth")
        body = await self._token_request(endpoint, data)
        normalized = self._normalize(body)
        await self.provider.set(account.id, normalized, expires_at=self._expiry(normalized))
        return normalized

    async def _refresh(self, platform: PublishingPlatform, refresh_token: str) -> dict[str, Any]:
        if platform == PublishingPlatform.YOUTUBE:
            endpoint = "https://oauth2.googleapis.com/token"
            data = {
                "client_id": self.settings.youtube_client_id,
                "client_secret": self.settings.youtube_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        elif platform == PublishingPlatform.TIKTOK:
            endpoint = "https://open.tiktokapis.com/v2/oauth/token/"
            data = {
                "client_key": self.settings.tiktok_client_key,
                "client_secret": self.settings.tiktok_client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            }
        else:
            return {}
        return self._normalize(await self._token_request(endpoint, data))

    async def _token_request(self, endpoint: str, data: dict[str, str]) -> dict[str, Any]:
        try:
            response = await self.client.post(endpoint, data=data)
        except (httpx.TimeoutException, httpx.NetworkError) as exc:
            raise ProviderTemporaryError("OAuth provider is temporarily unavailable") from exc
        if response.status_code >= 500:
            raise ProviderTemporaryError("OAuth provider is temporarily unavailable")
        if not response.is_success:
            raise AuthenticationError("OAuth token exchange was rejected")
        try:
            return dict(response.json())
        except ValueError as exc:
            raise AuthenticationError("OAuth provider returned invalid response") from exc

    @staticmethod
    def _normalize(body: dict[str, Any]) -> dict[str, Any]:
        result = dict(body)
        expires_in = result.get("expires_in")
        if expires_in is not None:
            result["expires_at"] = (
                datetime.now(UTC) + timedelta(seconds=int(expires_in))
            ).isoformat()
        return result

    @staticmethod
    def _expiry(credentials: dict[str, Any]) -> datetime | None:
        value = credentials.get("expires_at")
        if not value:
            return None
        parsed = datetime.fromisoformat(str(value))
        return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)
