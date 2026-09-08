import json
import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status

from app.api.dependencies import AssetDep
from app.models import SourceItem
from app.models.enums import AssetType
from app.schemas.assets import AssetCreate, AssetFromSourceCreate, AssetRead, AssetUpdate

router = APIRouter(prefix="/assets", tags=["assets"])


@router.get("", response_model=list[AssetRead])
async def list_assets(
    project_id: uuid.UUID,
    service: AssetDep,
    query: str | None = None,
    asset_type: AssetType | None = None,
    favorite: bool | None = None,
) -> object:
    return await service.list(
        project_id=project_id,
        query=query,
        asset_type=asset_type,
        favorite=favorite,
    )


@router.get("/{asset_id}", response_model=AssetRead)
async def get_asset(asset_id: uuid.UUID, service: AssetDep) -> object:
    return await service.get(asset_id)


@router.post("", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
async def upload_asset(
    service: AssetDep,
    file: Annotated[UploadFile, File()],
    project_id: Annotated[uuid.UUID, Form()],
    title: str = Form(""),
    description: str = Form(""),
    tags: str = Form("[]"),
    asset_type: Annotated[AssetType | None, Form()] = None,
) -> object:
    try:
        raw_tags = json.loads(tags)
    except json.JSONDecodeError as exc:
        raise HTTPException(status_code=422, detail="tags must be a JSON array") from exc
    maximum = service.settings.max_asset_size_mb * 1024 * 1024
    content = await file.read(maximum + 1)
    return await service.create(
        data=AssetCreate(
            project_id=project_id,
            title=title,
            description=description,
            tags=raw_tags,
            type=asset_type,
        ),
        filename=file.filename or "asset",
        mime_type=file.content_type or "application/octet-stream",
        content=content,
    )


@router.post("/from-source", response_model=AssetRead, status_code=status.HTTP_201_CREATED)
async def create_asset_from_source(data: AssetFromSourceCreate, service: AssetDep) -> object:
    source = await service.session.get(SourceItem, data.source_item_id)
    if source is None:
        from app.services.errors import NotFoundError

        raise NotFoundError("SourceItem not found")
    return await service.ingest_source(source)


@router.patch("/{asset_id}", response_model=AssetRead)
async def update_asset(asset_id: uuid.UUID, data: AssetUpdate, service: AssetDep) -> object:
    return await service.update(asset_id, data)


@router.post("/{asset_id}/analyze", response_model=AssetRead)
async def analyze_asset(asset_id: uuid.UUID, service: AssetDep) -> object:
    """Explicit action; upload alone never sends media to external vision."""
    return await service.analyze_with_vision(asset_id)


@router.delete("/{asset_id}", response_model=AssetRead)
async def archive_asset(asset_id: uuid.UUID, service: AssetDep) -> object:
    return await service.archive(asset_id)
