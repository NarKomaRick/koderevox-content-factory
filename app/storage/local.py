import asyncio
import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path


class LocalStorage:
    def __init__(self, root: str) -> None:
        self.root = Path(root).resolve()

    async def save(self, filename: str, content: bytes, category: str = "original") -> str:
        target, relative = self._target(filename, category)
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(target.write_bytes, content)
        return relative.as_posix()

    async def save_file(self, filename: str, source: Path, category: str = "original") -> str:
        target, relative = self._target(filename, category)
        await asyncio.to_thread(target.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(shutil.copyfile, source, target)
        return relative.as_posix()

    def _target(self, filename: str, category: str) -> tuple[Path, Path]:
        now = datetime.now(UTC)
        safe_category = (
            category
            if category in {"original", "processed", "render", "preview", "debug"}
            else "other"
        )
        relative = Path(
            str(now.year),
            f"{now.month:02d}",
            str(uuid.uuid4()),
            safe_category,
            Path(filename).name,
        )
        target = (self.root / relative).resolve()
        if self.root not in target.parents:
            raise ValueError("Unsafe storage path")
        return target, relative

    async def delete(self, path: str) -> None:
        target = self.resolve(path)
        if target.exists():
            await asyncio.to_thread(target.unlink)

    def resolve(self, path: str) -> Path:
        target = (self.root / path).resolve()
        if target != self.root and self.root not in target.parents:
            raise ValueError("Unsafe storage path")
        return target
