import hashlib
import json
import uuid

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Publication, PublishPackage
from app.models.enums import PublicationStatus, PublishPackageStatus


class PublicationNotificationService:
    def __init__(
        self,
        session: AsyncSession,
        bot_token: str,
        *,
        client: httpx.AsyncClient | None = None,
        base_url: str | None = None,
        proxy_url: str | None = None,
    ) -> None:
        self.session = session
        self.configured = bool(bot_token)
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(
            base_url=base_url or f"https://api.telegram.org/bot{bot_token}",
            timeout=20,
            proxy=proxy_url,
        )

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def notify_if_settled(self, package_id: uuid.UUID) -> bool:
        if not self.configured:
            return False
        publications = list(
            await self.session.scalars(
                select(Publication)
                .where(Publication.publish_package_id == package_id)
                .order_by(Publication.platform)
            )
        )
        terminal = {
            PublicationStatus.PUBLISHED,
            PublicationStatus.PUBLISHED_WITH_WARNING,
            PublicationStatus.FAILED,
            PublicationStatus.CANCELLED,
        }
        if not publications or any(item.status not in terminal for item in publications):
            return False
        chat_id = next(
            (
                item.publication_metadata.get("notify_chat_id")
                for item in publications
                if item.publication_metadata.get("notify_chat_id")
            ),
            None,
        )
        if chat_id is None:
            return False
        state = [(item.platform.value, item.status.value) for item in publications]
        fingerprint = hashlib.sha256(json.dumps(state).encode()).hexdigest()
        package = await self.session.get(PublishPackage, package_id)
        if package is None or package.package_metadata.get("notification_hash") == fingerprint:
            return False
        all_success = package.status == PublishPackageStatus.PUBLISHED
        lines = ["✅ Публикация завершена." if all_success else "⚠️ Публикация завершена частично."]
        icons = {
            PublicationStatus.PUBLISHED: "✅",
            PublicationStatus.PUBLISHED_WITH_WARNING: "⚠️",
            PublicationStatus.FAILED: "❌",
            PublicationStatus.CANCELLED: "🚫",
        }
        lines.extend(f"{item.platform.value}: {icons[item.status]}" for item in publications)
        try:
            response = await self.client.post(
                "sendMessage", data={"chat_id": str(chat_id), "text": "\n".join(lines)}
            )
        except httpx.HTTPError:
            return False
        if not response.is_success:
            return False
        package.package_metadata = {**package.package_metadata, "notification_hash": fingerprint}
        await self.session.commit()
        return True
