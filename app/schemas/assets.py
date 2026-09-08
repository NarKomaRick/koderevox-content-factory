import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models.enums import AssetStatus, AssetType


class AssetIntelligence(BaseModel):
    summary: str = Field(default="", max_length=2000)
    visible_elements: list[str] = Field(default_factory=list, max_length=50)
    products: list[str] = Field(default_factory=list, max_length=30)
    ui_elements: list[str] = Field(default_factory=list, max_length=50)
    technical_topics: list[str] = Field(default_factory=list, max_length=30)
    suggested_tags: list[str] = Field(default_factory=list, max_length=30)
    sensitive_content: list[str] = Field(default_factory=list, max_length=30)
    recommended_usage: list[str] = Field(default_factory=list, max_length=20)
    language: str | None = Field(default=None, max_length=50)
    framework: str | None = Field(default=None, max_length=100)
    visible_code: str | None = Field(default=None, max_length=20_000)


class AssetCreate(BaseModel):
    project_id: uuid.UUID
    source_item_id: uuid.UUID | None = None
    parent_asset_id: uuid.UUID | None = None
    type: AssetType | None = None
    title: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=10_000)
    tags: list[str] = Field(default_factory=list, max_length=100)
    favorite: bool = False
    license_type: str | None = Field(default=None, max_length=100)
    source: str | None = Field(default=None, max_length=1024)
    author: str | None = Field(default=None, max_length=255)
    attribution_required: bool = False


class AssetFromSourceCreate(BaseModel):
    source_item_id: uuid.UUID
    type: AssetType | None = None
    title: str = Field(default="", max_length=500)
    description: str = Field(default="", max_length=10_000)
    tags: list[str] = Field(default_factory=list, max_length=100)


class AssetUpdate(BaseModel):
    title: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=10_000)
    tags: list[str] | None = Field(default=None, max_length=100)
    favorite: bool | None = None
    license_type: str | None = Field(default=None, max_length=100)
    source: str | None = Field(default=None, max_length=1024)
    author: str | None = Field(default=None, max_length=255)
    attribution_required: bool | None = None


class AssetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    source_item_id: uuid.UUID | None
    parent_asset_id: uuid.UUID | None
    type: AssetType
    status: AssetStatus
    original_path: str
    processed_path: str | None
    thumbnail_path: str | None
    filename: str
    mime_type: str
    file_size: int
    width: int | None
    height: int | None
    duration: float | None
    title: str
    description: str
    tags: list[str]
    extracted_text: str | None
    analysis: dict[str, Any]
    favorite: bool
    license_type: str | None
    source: str | None
    author: str | None
    attribution_required: bool
    created_at: datetime
    updated_at: datetime
    usage_count: int = 0


class AssetSearchResult(BaseModel):
    items: list[AssetRead]
    total: int


class AssetUploadMetadata(BaseModel):
    filename: str
    mime_type: str
    size: int = Field(ge=1)

    @model_validator(mode="after")
    def filename_is_safe(self) -> "AssetUploadMetadata":
        if self.filename in {"", ".", ".."}:
            raise ValueError("filename is required")
        return self
