import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import OAuthState, PlatformAccount
from app.models.enums import PublishingPlatform
from app.schemas.publishing import OAuthStartResponse
from app.services.credentials import TokenManager
from app.services.errors import InvalidStateError, NotFoundError


class OAuthService:
    def __init__(
        self, session: AsyncSession, settings: Settings, token_manager: TokenManager
    ) -> None:
        self.session = session
        self.settings = settings
        self.token_manager = token_manager

    async def start(self, account_id: uuid.UUID) -> OAuthStartResponse:
        account = await self.session.get(PlatformAccount, account_id)
        if account is None:
            raise NotFoundError("PlatformAccount not found")
        if account.platform == PublishingPlatform.YOUTUBE and not all(
            (
                self.settings.youtube_client_id,
                self.settings.youtube_client_secret,
                self.settings.youtube_redirect_uri,
            )
        ):
            raise InvalidStateError("YouTube OAuth is not configured")
        if account.platform == PublishingPlatform.TIKTOK and not all(
            (
                self.settings.tiktok_client_key,
                self.settings.tiktok_client_secret,
                self.settings.tiktok_redirect_uri,
            )
        ):
            raise InvalidStateError("TikTok OAuth is not configured")
        if account.platform == PublishingPlatform.TELEGRAM:
            raise InvalidStateError("Telegram account does not use OAuth")
        state = secrets.token_urlsafe(32)
        expires_at = datetime.now(UTC) + timedelta(minutes=10)
        self.session.add(
            OAuthState(
                state_hash=self._hash(state),
                platform=account.platform,
                project_id=account.project_id,
                platform_account_id=account.id,
                expires_at=expires_at,
            )
        )
        await self.session.commit()
        if account.platform == PublishingPlatform.YOUTUBE:
            query = urlencode(
                {
                    "client_id": self.settings.youtube_client_id,
                    "redirect_uri": self.settings.youtube_redirect_uri,
                    "response_type": "code",
                    "scope": "https://www.googleapis.com/auth/youtube.upload https://www.googleapis.com/auth/youtube.force-ssl",
                    "access_type": "offline",
                    "prompt": "consent",
                    "state": state,
                }
            )
            endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
        elif account.platform == PublishingPlatform.TIKTOK:
            query = urlencode(
                {
                    "client_key": self.settings.tiktok_client_key,
                    "redirect_uri": self.settings.tiktok_redirect_uri,
                    "response_type": "code",
                    "scope": "user.info.basic,video.publish,video.upload",
                    "state": state,
                }
            )
            endpoint = "https://www.tiktok.com/v2/auth/authorize/"
        return OAuthStartResponse(authorization_url=f"{endpoint}?{query}", expires_at=expires_at)

    async def callback(
        self, platform: PublishingPlatform, state: str, code: str
    ) -> PlatformAccount:
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(OAuthState)
            .where(
                OAuthState.state_hash == self._hash(state),
                OAuthState.platform == platform,
                OAuthState.consumed_at.is_(None),
                OAuthState.expires_at > now,
            )
            .values(consumed_at=now)
            .returning(OAuthState.platform_account_id)
        )
        account_id = result.scalar_one_or_none()
        if account_id is None:
            await self.session.rollback()
            raise InvalidStateError("OAuth state is invalid, expired or already used")
        await self.session.commit()
        account = await self.session.get(PlatformAccount, account_id)
        if account is None:
            raise NotFoundError("PlatformAccount not found")
        credentials = await self.token_manager.exchange_code(account, code)
        if platform == PublishingPlatform.TIKTOK and credentials.get("open_id"):
            account.external_account_id = str(credentials["open_id"])
            await self.session.commit()
        return account

    @staticmethod
    def _hash(state: str) -> str:
        return hashlib.sha256(state.encode()).hexdigest()
