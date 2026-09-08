import uuid

import pytest
from PIL import Image

from app.core.config import Settings
from app.models import Project, VideoProject, VisualAsset
from app.models.enums import AssetStatus, AssetType, VideoProjectStatus
from app.schemas.assets import AssetCreate
from app.schemas.visual import VisualInsertion, VisualPlan
from app.services.assets import AssetService
from app.services.errors import InvalidStateError, PermanentProcessingError
from app.services.image_processor import ImageProcessor
from app.services.media import FFmpegMediaProcessor
from app.services.ocr import DisabledOCRProvider
from app.services.vision import OpenAICompatibleVisionProvider, PrivacyAwareVisionService
from app.services.visual_plans import VisualPlanService
from app.storage.local import LocalStorage


def phase4_settings(tmp_path, **updates) -> Settings:
    values = {
        "media_root": str(tmp_path / "media"),
        "render_temp_root": str(tmp_path / "render"),
        "ocr_enabled": False,
        "visual_min_gap_seconds": 2,
    }
    values.update(updates)
    return Settings(**values)


async def test_asset_image_ingestion_metadata_thumbnail_and_archive(session, tmp_path) -> None:
    project = (await session.scalars(__import__("sqlalchemy").select(Project))).one()
    image_path = tmp_path / "input.png"
    Image.new("RGB", (640, 360), "red").save(image_path)
    settings = phase4_settings(tmp_path)
    service = AssetService(
        session=session,
        storage=LocalStorage(settings.media_root),
        settings=settings,
        images=ImageProcessor(settings.max_image_pixels),
        media=FFmpegMediaProcessor(),
        ocr=DisabledOCRProvider(),
    )
    asset = await service.create(
        data=AssetCreate(
            project_id=project.id,
            title="BestWay booking",
            description="UI экрана записи",
            tags=["BestWay", "UI", "BestWay"],
        ),
        filename="../../booking.png",
        mime_type="image/png",
        content=image_path.read_bytes(),
    )
    assert asset.status == AssetStatus.READY
    assert (asset.width, asset.height) == (640, 360)
    assert asset.filename == "booking.png"
    assert asset.tags == ["BestWay", "UI"]
    assert asset.thumbnail_path
    assert service.storage.resolve(asset.thumbnail_path).is_file()
    assert (await service.list(project_id=project.id, query="booking"))[0].id == asset.id
    assert (await service.list(project_id=project.id, query="BestWay"))[0].id == asset.id
    archived = await service.archive(asset.id)
    assert archived.status == AssetStatus.ARCHIVED


async def test_asset_rejects_size_mime_and_huge_dimensions(session, tmp_path) -> None:
    project = (await session.scalars(__import__("sqlalchemy").select(Project))).one()
    settings = phase4_settings(tmp_path, max_asset_size_mb=1, max_image_pixels=1000000)
    service = AssetService(
        session=session,
        storage=LocalStorage(settings.media_root),
        settings=settings,
        images=ImageProcessor(settings.max_image_pixels),
        media=FFmpegMediaProcessor(),
        ocr=DisabledOCRProvider(),
    )
    with pytest.raises(PermanentProcessingError, match="Unsupported"):
        await service.create(
            data=AssetCreate(project_id=project.id),
            filename="payload.exe",
            mime_type="application/octet-stream",
            content=b"unsafe",
        )
    huge = tmp_path / "huge.png"
    Image.new("RGB", (1100, 1000), "white").save(huge)
    with pytest.raises(PermanentProcessingError, match="dimensions"):
        await service.create(
            data=AssetCreate(project_id=project.id),
            filename="huge.png",
            mime_type="image/png",
            content=huge.read_bytes(),
        )


class SpyExternalVision:
    external = True

    def __init__(self) -> None:
        self.called = False

    async def analyze(self, image_path, *, context, extracted_text):
        self.called = True
        raise AssertionError("must not be called")


async def test_external_vision_is_never_called_without_project_permission(
    session, tmp_path
) -> None:
    project = (await session.scalars(__import__("sqlalchemy").select(Project))).one()
    asset = VisualAsset(
        project_id=project.id,
        type=AssetType.SCREENSHOT,
        status=AssetStatus.READY,
        original_path="x.png",
        filename="x.png",
        mime_type="image/png",
        file_size=10,
    )
    spy = SpyExternalVision()
    with pytest.raises(InvalidStateError, match="disabled"):
        await PrivacyAwareVisionService(spy).analyze(asset, project, tmp_path / "x.png")
    assert spy.called is False


def valid_edit_plan() -> dict[str, object]:
    return {
        "clips": [
            {
                "source_start": 0,
                "source_end": 20,
                "source_segment_ids": [0],
                "purpose": "main",
            }
        ],
        "hook_text": "Технический разбор",
        "recommended_duration": 20,
        "reasoning_summary": "Цельный фрагмент",
        "framing": "center_crop",
        "pace": "medium",
    }


async def test_visual_plan_validation_project_isolation_overlap_and_usage(
    session, tmp_path
) -> None:
    project = (await session.scalars(__import__("sqlalchemy").select(Project))).one()
    asset = VisualAsset(
        project_id=project.id,
        type=AssetType.SCREENSHOT,
        status=AssetStatus.READY,
        original_path="x.png",
        filename="x.png",
        mime_type="image/png",
        file_size=10,
        title="BestWay booking",
        tags=["BestWay"],
    )
    video = VideoProject(
        project_id=project.id,
        source_item_id=uuid.uuid4(),
        status=VideoProjectStatus.READY_TO_RENDER,
        edit_plan=valid_edit_plan(),
    )
    session.add_all([asset, video])
    await session.commit()
    service = VisualPlanService(session, phase4_settings(tmp_path))
    insertion = VisualInsertion(start=4, end=7, asset_id=asset.id, layout="fullscreen")
    updated = await service.replace(video.id, VisualPlan(insertions=[insertion]))
    assert updated.visual_plan["insertions"][0]["layout"] == "fullscreen"
    await service.record_usage(video.id, VisualPlan(insertions=[insertion]))
    await service.record_usage(video.id, VisualPlan(insertions=[insertion]))
    await session.commit()
    from sqlalchemy import func, select

    from app.models import AssetUsage

    assert await session.scalar(select(func.count(AssetUsage.id))) == 1
    overlap = VisualPlan(
        insertions=[
            insertion,
            VisualInsertion(start=6, end=9, asset_id=asset.id, layout="picture_in_picture"),
        ]
    )
    with pytest.raises(InvalidStateError, match="Overlapping"):
        await service.replace(video.id, overlap)


async def test_retrieval_is_project_scoped(session, tmp_path) -> None:
    projects = [
        Project(name="Other", description="", brand_context="", target_audience=""),
    ]
    session.add_all(projects)
    await session.flush()
    other = VisualAsset(
        project_id=projects[0].id,
        type=AssetType.SCREENSHOT,
        status=AssetStatus.READY,
        original_path="secret.png",
        filename="secret.png",
        mime_type="image/png",
        file_size=1,
        title="BestWay secret",
    )
    session.add(other)
    await session.commit()
    service = VisualPlanService(session, phase4_settings(tmp_path))
    result = await service._retrieve(uuid.uuid4(), ["BestWay"])
    assert result == []


class SuccessfulOCR:
    async def extract(self, image_path) -> str:
        return "const api = await BestWay.booking()"


async def test_ocr_text_is_saved_and_searchable(session, tmp_path) -> None:
    project = (await session.scalars(__import__("sqlalchemy").select(Project))).one()
    image = tmp_path / "code.png"
    Image.new("RGB", (800, 600), "#222222").save(image)
    settings = phase4_settings(tmp_path)
    service = AssetService(
        session=session,
        storage=LocalStorage(settings.media_root),
        settings=settings,
        images=ImageProcessor(),
        media=FFmpegMediaProcessor(),
        ocr=SuccessfulOCR(),
    )
    asset = await service.create(
        data=AssetCreate(project_id=project.id, type=AssetType.SCREENSHOT),
        filename="code.png",
        mime_type="image/png",
        content=image.read_bytes(),
    )
    assert "BestWay.booking" in (asset.extracted_text or "")
    assert (await service.list(project_id=project.id, query="BestWay.booking"))[0].id == asset.id


async def test_openai_compatible_vision_structured_parsing(tmp_path) -> None:
    import httpx

    image = tmp_path / "screen.png"
    Image.new("RGB", (10, 10), "white").save(image)

    async def handler(request: httpx.Request) -> httpx.Response:
        assert "image_url" in request.content.decode()
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": '{"summary":"BestWay UI","suggested_tags":["BestWay","UI"]}'
                        }
                    }
                ]
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleVisionProvider(
        base_url="https://vision.invalid/v1",
        api_key="secret",
        model="vision",
        client=client,
    )
    result = await provider.analyze(image, context="booking", extracted_text="Запись")
    assert result.summary == "BestWay UI"
    assert result.suggested_tags == ["BestWay", "UI"]
    await client.aclose()
