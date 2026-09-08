import asyncio
import tempfile
from pathlib import Path

import httpx
import structlog

from app.models import VideoProject
from app.models.enums import SubtitlePreset
from app.services.video_editor import FFmpegVideoEditor
from app.storage.base import Storage

logger = structlog.get_logger()


class PreviewDeliveryService:
    def __init__(
        self,
        *,
        bot_token: str,
        storage: Storage,
        maximum_size_bytes: int,
        editor: FFmpegVideoEditor,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.bot_token = bot_token
        self.storage = storage
        self.maximum_size_bytes = maximum_size_bytes
        self.editor = editor
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=120)

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def deliver(self, project: VideoProject, chat_id: int) -> str | None:
        if not self.bot_token or not project.final_path:
            return None
        final = self.storage.resolve(project.final_path)
        selected = final
        stored_preview = project.final_path
        if final.stat().st_size > self.maximum_size_bytes:
            with tempfile.TemporaryDirectory(prefix="content-factory-preview-") as temporary:
                compressed = Path(temporary) / "preview.mp4"
                await self.editor.compress_preview(final, compressed)
                if compressed.stat().st_size > self.maximum_size_bytes:
                    await self.editor.compress_preview(final, compressed, width=540, height=960)
                stored_preview = await self.storage.save_file(
                    f"{project.id}-preview.mp4", compressed, "preview"
                )
                selected = self.storage.resolve(stored_preview)
        if selected.stat().st_size > self.maximum_size_bytes:
            raise RuntimeError("Compressed preview still exceeds Telegram size limit")
        data = await asyncio.to_thread(selected.read_bytes)
        plan = project.edit_plan
        duration = project.metrics.get("output_duration", project.target_duration)
        style = project.subtitle_style.get("preset", SubtitlePreset.TECH.value).upper()
        caption = (
            "🎬 Short готов\n\n"
            f"{self._time(float(duration))}\n"
            f"Hook: {plan.get('hook_text', '—')}\n"
            f"Style: {style}"
        )
        keyboard = {
            "inline_keyboard": [
                [{"text": "✅ Одобрить", "callback_data": f"video_approve:{project.id}"}],
                [
                    {"text": "✂️ Монтаж", "callback_data": f"video_edit:{project.id}"},
                    {"text": "📝 Текст", "callback_data": f"video_text:{project.id}"},
                    {"text": "🎨 Стиль", "callback_data": f"video_style:{project.id}"},
                ],
                [
                    {"text": "🔄 Пересобрать", "callback_data": f"video_rerender:{project.id}"},
                    {"text": "🗑 Удалить", "callback_data": f"video_archive:{project.id}"},
                ],
            ]
        }
        response = await self.client.post(
            f"https://api.telegram.org/bot{self.bot_token}/sendVideo",
            data={
                "chat_id": str(chat_id),
                "caption": caption,
                "supports_streaming": "true",
                "reply_markup": __import__("json").dumps(keyboard, ensure_ascii=False),
            },
            files={"video": ("preview.mp4", data, "video/mp4")},
        )
        response.raise_for_status()
        await logger.ainfo(
            "video_preview_delivered",
            video_project_id=str(project.id),
            chat_id=chat_id,
            compressed=selected != final,
        )
        return stored_preview

    async def failed(self, project: VideoProject, chat_id: int) -> None:
        if not self.bot_token:
            return
        keyboard = {
            "inline_keyboard": [
                [{"text": "🔄 Повторить", "callback_data": f"video_rerender:{project.id}"}],
                [{"text": "⚙️ Упростить рендер", "callback_data": f"video_simple:{project.id}"}],
                [{"text": "🗑 Удалить", "callback_data": f"video_archive:{project.id}"}],
            ]
        }
        response = await self.client.post(
            f"https://api.telegram.org/bot{self.bot_token}/sendMessage",
            json={
                "chat_id": chat_id,
                "text": "⚠️ Не удалось собрать ролик.",
                "reply_markup": keyboard,
            },
        )
        response.raise_for_status()

    @staticmethod
    def _time(seconds: float) -> str:
        total = round(seconds)
        return f"{total // 60:02d}:{total % 60:02d}"
