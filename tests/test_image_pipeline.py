import asyncio

from PIL import Image

from app.ai.mock import MockAIProvider
from app.models.enums import SourceStatus, SourceType
from app.schemas.api import SourceCreate
from app.services.document_processor import DocumentProcessor
from app.services.image_processor import ImageProcessor
from app.services.inbox import InboxService
from app.services.processing import SourceProcessingService
from app.storage.local import LocalStorage


class NoVisionAI(MockAIProvider):
    def __init__(self) -> None:
        self.calls = 0

    async def generate_structured(self, **kwargs):
        self.calls += 1
        return await super().generate_structured(**kwargs)


async def test_image_without_vision_is_saved_with_dimensions(session, tmp_path) -> None:
    image_path = tmp_path / "image.png"
    await asyncio.to_thread(Image.new("RGB", (640, 360)).save, image_path)
    storage = LocalStorage(str(tmp_path / "storage"))
    stored = await storage.save_file("image.png", image_path)
    source, _ = await InboxService(session).register_source(
        SourceCreate(
            telegram_user_id=42,
            telegram_update_id=1200,
            type=SourceType.IMAGE,
            local_file_path=stored,
            original_filename="screenshot.png",
            mime_type="image/png",
        )
    )
    ai = NoVisionAI()
    service = SourceProcessingService(
        session=session,
        ai_provider=ai,
        storage=storage,
        media_processor=object(),  # type: ignore[arg-type]
        stt_provider=object(),  # type: ignore[arg-type]
        document_processor=DocumentProcessor(),
        image_processor=ImageProcessor(),
        link_processor=object(),  # type: ignore[arg-type]
        telegram_media=None,
    )

    result = await service.process(source.id)

    assert result.processing_status == SourceStatus.READY
    assert result.source_metadata["image"]["width"] == 640
    assert result.source_metadata["image"]["height"] == 360
    assert result.content_potential_score is None
    assert ai.calls == 0
