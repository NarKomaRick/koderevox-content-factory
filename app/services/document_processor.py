import asyncio
from pathlib import Path

from pypdf import PdfReader

from app.schemas.processing import DocumentContent
from app.services.errors import PermanentProcessingError


class DocumentProcessor:
    def __init__(self, max_chars: int = 100_000) -> None:
        self.max_chars = max_chars

    async def extract(self, path: Path, mime_type: str | None = None) -> DocumentContent:
        suffix = path.suffix.lower()
        if suffix in {".txt", ".md"} or mime_type in {"text/plain", "text/markdown"}:
            return await asyncio.to_thread(self._extract_text, path)
        if suffix == ".pdf" or mime_type == "application/pdf":
            return await asyncio.to_thread(self._extract_pdf, path)
        raise PermanentProcessingError("Unsupported document type")

    def _extract_text(self, path: Path) -> DocumentContent:
        text = path.read_text(encoding="utf-8", errors="replace")
        return self._limited(text)

    def _extract_pdf(self, path: Path) -> DocumentContent:
        reader = PdfReader(path)
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages).strip()
        if not text:
            return DocumentContent(
                text="",
                page_count=len(reader.pages),
                extraction_error="PDF contains no extractable text; OCR was not attempted",
            )
        result = self._limited(text)
        result.page_count = len(reader.pages)
        return result

    def _limited(self, text: str) -> DocumentContent:
        truncated = len(text) > self.max_chars
        return DocumentContent(text=text[: self.max_chars], truncated=truncated)
