import asyncio

import httpx
import pytest

from app.services.document_processor import DocumentProcessor
from app.services.errors import PermanentProcessingError
from app.services.telegram_media import TelegramMediaService
from app.storage.local import LocalStorage


async def test_text_document_is_extracted_and_truncated(tmp_path) -> None:
    path = tmp_path / "note.md"
    await asyncio.to_thread(path.write_text, "abcdefghij", encoding="utf-8")

    result = await DocumentProcessor(max_chars=5).extract(path, "text/markdown")

    assert result.text == "abcde"
    assert result.truncated is True


async def test_pdf_without_text_reports_no_ocr(tmp_path) -> None:
    from pypdf import PdfWriter

    path = tmp_path / "scan.pdf"

    def create_blank_pdf() -> None:
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        with path.open("wb") as output:
            writer.write(output)

    await asyncio.to_thread(create_blank_pdf)

    result = await DocumentProcessor().extract(path, "application/pdf")

    assert result.text == ""
    assert result.page_count == 1
    assert "OCR was not attempted" in (result.extraction_error or "")


async def test_telegram_download_uses_safe_storage_name(tmp_path) -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/getFile"):
            return httpx.Response(
                200,
                json={
                    "ok": True,
                    "result": {"file_path": "voice/file_1.ogg", "file_size": 4},
                },
                request=request,
            )
        return httpx.Response(200, content=b"opus", request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    storage = LocalStorage(str(tmp_path))
    service = TelegramMediaService(
        bot_token="test", storage=storage, max_size_bytes=100, client=client
    )

    relative, metadata = await service.download(
        file_id="file",
        original_filename="../../unsafe.ogg",
        mime_type="audio/ogg",
        declared_size=4,
    )

    assert await asyncio.to_thread(storage.resolve(relative).read_bytes) == b"opus"
    assert ".." not in relative
    assert "/original/" in f"/{relative}"
    assert metadata["downloaded_size"] == 4
    await client.aclose()


async def test_telegram_download_rejects_declared_oversize(tmp_path) -> None:
    service = TelegramMediaService(
        bot_token="test", storage=LocalStorage(str(tmp_path)), max_size_bytes=10
    )
    with pytest.raises(PermanentProcessingError):
        await service.download(
            file_id="file",
            original_filename="voice.ogg",
            mime_type="audio/ogg",
            declared_size=11,
        )
