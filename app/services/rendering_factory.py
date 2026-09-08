from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.services.rendering import VideoRenderService
from app.storage.local import LocalStorage


def create_render_service(session: AsyncSession, settings: Settings) -> VideoRenderService:
    return VideoRenderService(
        session=session,
        storage=LocalStorage(settings.media_root),
        settings=settings,
    )
