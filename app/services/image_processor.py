import asyncio
import hashlib
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

from app.services.errors import PermanentProcessingError


class ImageProcessor:
    def __init__(self, max_pixels: int = 40_000_000) -> None:
        self.max_pixels = max_pixels

    async def metadata(self, path: Path) -> dict[str, object]:
        return await asyncio.to_thread(self._metadata_sync, path)

    async def prepare(
        self,
        source: Path,
        destination: Path,
        *,
        width: int,
        height: int,
        mode: str = "fit",
        quality: int = 92,
    ) -> Path:
        await asyncio.to_thread(
            self._prepare_sync, source, destination, width, height, mode, quality
        )
        return destination

    async def thumbnail(
        self, source: Path, destination: Path, *, size: tuple[int, int] = (480, 480)
    ) -> Path:
        return await self.prepare(
            source, destination, width=size[0], height=size[1], mode="fit", quality=85
        )

    @staticmethod
    def cache_key(asset_id: object, settings: dict[str, object]) -> str:
        payload = f"{asset_id}:{sorted(settings.items())}".encode()
        return hashlib.sha256(payload).hexdigest()[:24]

    def _metadata_sync(self, path: Path) -> dict[str, object]:
        try:
            with Image.open(path) as image:
                self._validate_pixels(image.width, image.height)
                return {
                    "width": image.width,
                    "height": image.height,
                    "image_format": image.format,
                    "image_mode": image.mode,
                    "orientation": image.getexif().get(274),
                }
        except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as exc:
            raise PermanentProcessingError("Unsafe or invalid image") from exc

    def _prepare_sync(
        self,
        source: Path,
        destination: Path,
        width: int,
        height: int,
        mode: str,
        quality: int,
    ) -> None:
        try:
            with Image.open(source) as opened:
                self._validate_pixels(opened.width, opened.height)
                image = ImageOps.exif_transpose(opened).convert("RGB")
                if mode == "crop":
                    image = ImageOps.fit(image, (width, height), Image.Resampling.LANCZOS)
                elif mode == "fit":
                    image.thumbnail((width, height), Image.Resampling.LANCZOS)
                    canvas = Image.new("RGB", (width, height), "#10141b")
                    canvas.paste(image, ((width - image.width) // 2, (height - image.height) // 2))
                    image = canvas
                else:
                    raise ValueError("mode must be 'fit' or 'crop'")
                destination.parent.mkdir(parents=True, exist_ok=True)
                image.save(destination, quality=quality, optimize=True)
        except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as exc:
            raise PermanentProcessingError("Image processing failed") from exc

    def _validate_pixels(self, width: int, height: int) -> None:
        if width <= 0 or height <= 0 or width * height > self.max_pixels:
            raise PermanentProcessingError("Image dimensions exceed configured limits")
