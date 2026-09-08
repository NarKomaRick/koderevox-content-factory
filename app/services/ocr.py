import asyncio
import shutil
from pathlib import Path
from typing import Protocol

import structlog

logger = structlog.get_logger()


class OCRProvider(Protocol):
    async def extract(self, image_path: Path) -> str: ...


class DisabledOCRProvider:
    async def extract(self, image_path: Path) -> str:
        return ""


class TesseractOCRProvider:
    def __init__(self, language: str = "rus+eng") -> None:
        self.language = language

    async def extract(self, image_path: Path) -> str:
        executable = shutil.which("tesseract")
        if executable is None:
            await logger.awarning("ocr_unavailable", provider="tesseract")
            return ""
        process = await asyncio.create_subprocess_exec(
            executable,
            str(image_path),
            "stdout",
            "-l",
            self.language,
            "--psm",
            "6",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            await logger.awarning("ocr_failed", stderr=stderr.decode(errors="replace")[-1000:])
            return ""
        return stdout.decode("utf-8", errors="replace").strip()[:100_000]


def create_ocr_provider(*, enabled: bool, language: str) -> OCRProvider:
    return TesseractOCRProvider(language) if enabled else DisabledOCRProvider()
