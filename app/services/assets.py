import asyncio
import builtins
import re
import tempfile
import time
import uuid
from collections.abc import Sequence
from pathlib import Path

import structlog
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models import AssetUsage, Project, SourceItem, VisualAsset
from app.models.enums import AssetStatus, AssetType, SourceType
from app.schemas.assets import AssetCreate, AssetIntelligence, AssetUpdate
from app.services.errors import InvalidStateError, NotFoundError, PermanentProcessingError
from app.services.image_processor import ImageProcessor
from app.services.media import FFmpegMediaProcessor
from app.services.ocr import OCRProvider
from app.services.vision import PrivacyAwareVisionService
from app.storage.base import Storage

logger = structlog.get_logger()

IMAGE_MIMES = {"image/jpeg", "image/png", "image/webp"}
SVG_MIMES = {"image/svg+xml"}
VIDEO_MIMES = {"video/mp4", "video/quicktime", "video/webm", "video/x-matroska"}
TEXT_MIMES = {"text/plain", "text/markdown", "text/x-python", "application/json"}
ALLOWED_MIMES = IMAGE_MIMES | SVG_MIMES | VIDEO_MIMES | TEXT_MIMES | {"application/pdf"}
CODE_SUFFIXES = {".py", ".js", ".ts", ".tsx", ".jsx", ".kt", ".swift", ".sql", ".json"}


class AssetService:
    def __init__(
        self,
        *,
        session: AsyncSession,
        storage: Storage,
        settings: Settings,
        images: ImageProcessor,
        media: FFmpegMediaProcessor,
        ocr: OCRProvider,
        vision: PrivacyAwareVisionService | None = None,
    ) -> None:
        self.session = session
        self.storage = storage
        self.settings = settings
        self.images = images
        self.media = media
        self.ocr = ocr
        self.vision = vision

    async def list(
        self,
        *,
        project_id: uuid.UUID,
        query: str | None = None,
        asset_type: AssetType | None = None,
        favorite: bool | None = None,
        limit: int = 50,
    ) -> Sequence[VisualAsset]:
        statement = select(VisualAsset).where(
            VisualAsset.project_id == project_id,
            VisualAsset.status != AssetStatus.ARCHIVED,
        )
        if asset_type is not None:
            statement = statement.where(VisualAsset.type == asset_type)
        if favorite is not None:
            statement = statement.where(VisualAsset.favorite == favorite)
        if query:
            pattern = f"%{query.strip()}%"
            statement = statement.where(
                or_(
                    VisualAsset.title.ilike(pattern),
                    VisualAsset.description.ilike(pattern),
                    VisualAsset.extracted_text.ilike(pattern),
                    cast(VisualAsset.tags, String).ilike(pattern),
                )
            )
        return (
            await self.session.scalars(
                statement.order_by(
                    VisualAsset.favorite.desc(), VisualAsset.created_at.desc()
                ).limit(min(limit, 200))
            )
        ).all()

    async def get(self, asset_id: uuid.UUID) -> VisualAsset:
        asset = await self.session.get(VisualAsset, asset_id)
        if asset is None:
            raise NotFoundError("VisualAsset not found")
        return asset

    async def create(
        self,
        *,
        data: AssetCreate,
        filename: str,
        mime_type: str,
        content: bytes,
    ) -> VisualAsset:
        if len(content) > self.settings.max_asset_size_mb * 1024 * 1024:
            raise PermanentProcessingError("Asset exceeds MAX_ASSET_SIZE_MB")
        if mime_type not in ALLOWED_MIMES:
            raise PermanentProcessingError("Unsupported asset type")
        project = await self.session.get(Project, data.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        safe_name = self._safe_filename(filename)
        if mime_type in SVG_MIMES:
            self._validate_svg(content)
        original_path = await self.storage.save(safe_name, content, "original")
        asset = VisualAsset(
            project_id=data.project_id,
            source_item_id=data.source_item_id,
            parent_asset_id=data.parent_asset_id,
            type=data.type or self._infer_type(safe_name, mime_type, data.description),
            status=AssetStatus.PROCESSING,
            original_path=original_path,
            filename=safe_name,
            mime_type=mime_type,
            file_size=len(content),
            title=data.title.strip() or Path(safe_name).stem,
            description=data.description.strip(),
            tags=self._normalize_tags(data.tags),
            favorite=data.favorite,
            license_type=data.license_type,
            source=data.source,
            author=data.author,
            attribution_required=data.attribution_required,
        )
        self.session.add(asset)
        await self.session.flush()
        await self._prepare(asset, project)
        await self.session.commit()
        await self.session.refresh(asset)
        return asset

    async def ingest_source(self, source: SourceItem) -> VisualAsset | None:
        if source.type not in {SourceType.IMAGE, SourceType.VIDEO, SourceType.DOCUMENT}:
            return None
        existing = await self.session.scalar(
            select(VisualAsset).where(VisualAsset.source_item_id == source.id)
        )
        if existing is not None:
            return existing
        if not source.local_file_path:
            return None
        path = self.storage.resolve(source.local_file_path)
        if not path.is_file():
            return None
        data = AssetCreate(
            project_id=source.project_id,
            source_item_id=source.id,
            title=source.topic or source.original_filename or path.stem,
            description=source.original_text or source.summary or "",
            tags=list(source.content_analysis.get("keywords", [])),
        )
        return await self.create(
            data=data,
            filename=source.original_filename or path.name,
            mime_type=source.mime_type or self._mime_from_source(source),
            content=await asyncio.to_thread(path.read_bytes),
        )

    async def update(self, asset_id: uuid.UUID, data: AssetUpdate) -> VisualAsset:
        asset = await self.get(asset_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            if field == "tags" and value is not None:
                value = self._normalize_tags(value)
            setattr(asset, field, value)
        await self.session.commit()
        await self.session.refresh(asset)
        return asset

    async def archive(self, asset_id: uuid.UUID) -> VisualAsset:
        asset = await self.get(asset_id)
        asset.status = AssetStatus.ARCHIVED
        await self.session.commit()
        await self.session.refresh(asset)
        return asset

    async def analyze_with_vision(self, asset_id: uuid.UUID) -> VisualAsset:
        asset = await self.get(asset_id)
        if self.vision is None:
            raise InvalidStateError("Vision provider is disabled")
        if asset.mime_type not in IMAGE_MIMES:
            raise InvalidStateError("Vision currently supports raster images only")
        project = await self.session.get(Project, asset.project_id)
        if project is None:
            raise NotFoundError("Project not found")
        started = time.monotonic()
        intelligence = await self.vision.analyze(
            asset, project, self.storage.resolve(asset.original_path)
        )
        asset.analysis = {
            **asset.analysis,
            **intelligence.model_dump(mode="json"),
            "vision_duration": round(time.monotonic() - started, 3),
        }
        asset.tags = self._normalize_tags([*asset.tags, *intelligence.suggested_tags])
        await self.session.commit()
        await self.session.refresh(asset)
        return asset

    async def usage_count(self, asset_id: uuid.UUID) -> int:
        return int(
            await self.session.scalar(
                select(func.count(AssetUsage.id)).where(AssetUsage.asset_id == asset_id)
            )
            or 0
        )

    async def _prepare(self, asset: VisualAsset, project: Project) -> None:
        started = time.monotonic()
        source = self.storage.resolve(asset.original_path)
        try:
            if asset.mime_type in IMAGE_MIMES:
                metadata = await self.images.metadata(source)
                asset.width = self._as_int(metadata.get("width"))
                asset.height = self._as_int(metadata.get("height"))
                with tempfile.TemporaryDirectory(prefix="asset-prepare-") as temp_dir:
                    preview = Path(temp_dir) / "thumbnail.jpg"
                    await self.images.thumbnail(source, preview)
                    asset.thumbnail_path = await self.storage.save_file(
                        f"{asset.id}.jpg", preview, "preview"
                    )
                ocr_started = time.monotonic()
                asset.extracted_text = await self.ocr.extract(source) or None
                local_intelligence = self._local_intelligence(asset)
                asset.analysis = {
                    **asset.analysis,
                    **local_intelligence.model_dump(mode="json"),
                }
                if local_intelligence.visible_code:
                    asset.type = AssetType.CODE
                asset.analysis = {
                    **asset.analysis,
                    "ocr_duration": round(time.monotonic() - ocr_started, 3),
                }
            elif asset.mime_type in VIDEO_MIMES:
                metadata = self.media.useful_metadata(await self.media.probe(source))
                asset.width = self._as_int(metadata.get("width"))
                asset.height = self._as_int(metadata.get("height"))
                asset.duration = self._as_float(metadata.get("duration_seconds"))
                if asset.duration and asset.duration > self.settings.max_asset_duration:
                    raise PermanentProcessingError("Asset exceeds MAX_ASSET_DURATION")
                asset.analysis = self._local_intelligence(asset).model_dump(mode="json")
            elif asset.mime_type in TEXT_MIMES or source.suffix.lower() in CODE_SUFFIXES:
                content = await asyncio.to_thread(source.read_text, errors="replace")
                asset.extracted_text = content[:100_000]
                asset.type = AssetType.CODE
                asset.analysis = AssetIntelligence(
                    summary=asset.description or asset.title,
                    visible_code=asset.extracted_text[:20_000],
                    suggested_tags=[source.suffix.lstrip(".")],
                    recommended_usage=["code_card"],
                ).model_dump(mode="json")
            asset.status = AssetStatus.READY
            asset.analysis = {
                **asset.analysis,
                "asset_prepare_duration": round(time.monotonic() - started, 3),
            }
        except Exception as exc:
            asset.status = AssetStatus.FAILED
            asset.analysis = {**asset.analysis, "error": type(exc).__name__}
            raise

    @staticmethod
    def _safe_filename(filename: str) -> str:
        name = Path(filename).name.replace("\x00", "").strip()
        name = re.sub(r"[^\w.()\- ]+", "_", name, flags=re.UNICODE)[:240]
        if not name or name in {".", ".."}:
            raise PermanentProcessingError("Unsafe filename")
        return name

    @staticmethod
    def _validate_svg(content: bytes) -> None:
        if len(content) > 5 * 1024 * 1024:
            raise PermanentProcessingError("SVG is too large")
        lowered = content[:5_000_000].lower()
        forbidden = (
            b"<script",
            b"<!entity",
            b"<!doctype",
            b"<foreignobject",
            b"javascript:",
            b"xlink:href=",
            b" href=",
            b"url(",
        )
        if any(token in lowered for token in forbidden):
            raise PermanentProcessingError("Unsafe SVG content")

    @staticmethod
    def _normalize_tags(tags: Sequence[str]) -> builtins.list[str]:
        normalized = [tag.strip()[:80] for tag in tags if tag.strip()]
        return list(dict.fromkeys(normalized))[:100]

    @staticmethod
    def _as_int(value: object) -> int | None:
        if isinstance(value, (int, float, str)) and str(value):
            converted = int(value)
            return converted or None
        return None

    @staticmethod
    def _as_float(value: object) -> float | None:
        if isinstance(value, (int, float, str)) and str(value):
            converted = float(value)
            return converted or None
        return None

    @staticmethod
    def _infer_type(filename: str, mime_type: str, description: str) -> AssetType:
        lower = f"{filename} {description}".casefold()
        suffix = Path(filename).suffix.lower()
        if suffix in CODE_SUFFIXES or mime_type in TEXT_MIMES:
            return AssetType.CODE
        if mime_type in VIDEO_MIMES:
            is_screen = "screen" in lower or "экран" in lower
            return AssetType.SCREEN_RECORDING if is_screen else AssetType.VIDEO
        if "logo" in lower or "логотип" in lower:
            return AssetType.LOGO
        if "diagram" in lower or "схем" in lower:
            return AssetType.DIAGRAM
        if "screenshot" in lower or "скрин" in lower or "ui" in lower:
            return AssetType.SCREENSHOT
        return AssetType.IMAGE

    @staticmethod
    def _local_intelligence(asset: VisualAsset) -> AssetIntelligence:
        context = "\n".join(
            filter(None, [asset.title, asset.description, asset.extracted_text or ""])
        )
        lowered = context.casefold()
        sensitive: list[str] = []
        if re.search(r"[\w.+-]+@[\w.-]+\.[a-z]{2,}", context, re.IGNORECASE):
            sensitive.append("email")
        if re.search(r"(?:api[_ -]?key|bearer\s+[a-z0-9._-]+|secret[_ -]?key)", lowered):
            sensitive.append("credentials")
        if re.search(r"(?:\+7|8)[\s(\-]*\d{3}", context):
            sensitive.append("phone")
        code_markers = sum(
            marker in lowered
            for marker in ("import ", "def ", "class ", "const ", "function ", "=>", "await ")
        )
        language = None
        if "def " in lowered or "import " in lowered:
            language = "python"
        elif "const " in lowered or "=>" in lowered:
            language = "typescript/javascript"
        framework = next(
            (
                name
                for name in ("React Native", "FastAPI", "PostgreSQL", "1С")
                if name.casefold() in lowered
            ),
            None,
        )
        known_topics = (
            "REST API",
            "React Native",
            "FastAPI",
            "PostgreSQL",
            "1С",
            "BestWay",
            "Altair",
        )
        topics = [topic for topic in known_topics if topic.casefold() in lowered]
        return AssetIntelligence(
            summary=asset.description or asset.title,
            visible_elements=[],
            technical_topics=topics,
            suggested_tags=asset.tags,
            sensitive_content=sensitive,
            recommended_usage=["code_card"] if code_markers >= 2 else ["illustration"],
            language=language if code_markers >= 2 else None,
            framework=framework,
            visible_code=(asset.extracted_text or "")[:20_000] if code_markers >= 2 else None,
        )

    @staticmethod
    def _mime_from_source(source: SourceItem) -> str:
        if source.type == SourceType.IMAGE:
            return "image/jpeg"
        if source.type == SourceType.VIDEO:
            return "video/mp4"
        return "application/pdf"
