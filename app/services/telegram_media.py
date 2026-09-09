import mimetypes
import tempfile
from pathlib import Path
from typing import Any

import aiofiles
import httpx

from app.services.errors import PermanentProcessingError, TemporaryProcessingError
from app.storage.base import Storage


class TelegramMediaService:
    def __init__(
        self,
        *,
        bot_token: str,
        storage: Storage,
        max_size_bytes: int,
        proxy_url: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.bot_token = bot_token
        self.storage = storage
        self.max_size_bytes = max_size_bytes
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=120, proxy=proxy_url or None)

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def download(
        self,
        *,
        file_id: str,
        original_filename: str | None,
        mime_type: str | None,
        declared_size: int | None,
    ) -> tuple[str, dict[str, Any]]:
        if declared_size is not None and declared_size > self.max_size_bytes:
            raise PermanentProcessingError("Telegram file exceeds configured size limit")
        try:
            metadata_response = await self.client.get(
                f"https://api.telegram.org/bot{self.bot_token}/getFile",
                params={"file_id": file_id},
            )
            metadata_response.raise_for_status()
            remote = metadata_response.json()["result"]
            remote_path = str(remote["file_path"])
            remote_size = int(remote.get("file_size") or declared_size or 0)
            if remote_size > self.max_size_bytes:
                raise PermanentProcessingError("Telegram file exceeds configured size limit")
            safe_name = self._safe_filename(original_filename, remote_path, mime_type)
            with tempfile.TemporaryDirectory(prefix="content-factory-download-") as temp_dir:
                temporary = Path(temp_dir) / safe_name
                await self._stream_to_file(remote_path, temporary)
                saved_path = await self.storage.save_file(safe_name, temporary, "original")
            return saved_path, {"telegram_remote_path": remote_path, "downloaded_size": remote_size}
        except (KeyError, TypeError, ValueError) as exc:
            raise PermanentProcessingError("Invalid Telegram file metadata") from exc
        except httpx.TimeoutException as exc:
            raise TemporaryProcessingError("Telegram download timed out") from exc
        except httpx.TransportError as exc:
            raise TemporaryProcessingError("Telegram download failed") from exc
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code >= 500:
                raise TemporaryProcessingError(
                    "Telegram service is temporarily unavailable"
                ) from exc
            raise PermanentProcessingError("Telegram rejected the file request") from exc

    async def _stream_to_file(self, remote_path: str, destination: Path) -> None:
        url = f"https://api.telegram.org/file/bot{self.bot_token}/{remote_path}"
        total = 0
        async with self.client.stream("GET", url) as response:
            response.raise_for_status()
            async with aiofiles.open(destination, "wb") as output:
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > self.max_size_bytes:
                        raise PermanentProcessingError(
                            "Telegram file exceeds configured size limit"
                        )
                    await output.write(chunk)

    @staticmethod
    def _safe_filename(
        original_filename: str | None, remote_path: str, mime_type: str | None
    ) -> str:
        candidate = Path(original_filename or "").name
        suffix = Path(candidate).suffix or Path(remote_path).suffix
        if not suffix and mime_type:
            suffix = mimetypes.guess_extension(mime_type) or ""
        stem = Path(candidate).stem[:80] if candidate else "telegram-media"
        return f"{stem or 'telegram-media'}{suffix.lower()}"
