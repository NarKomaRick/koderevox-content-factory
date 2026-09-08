import asyncio
from pathlib import Path

from PIL import Image


class ImageProcessor:
    async def metadata(self, path: Path) -> dict[str, object]:
        return await asyncio.to_thread(self._metadata_sync, path)

    def _metadata_sync(self, path: Path) -> dict[str, object]:
        with Image.open(path) as image:
            return {
                "width": image.width,
                "height": image.height,
                "image_format": image.format,
                "image_mode": image.mode,
            }
