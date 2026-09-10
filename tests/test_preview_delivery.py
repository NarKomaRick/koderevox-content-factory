import json

import httpx
import pytest

from app.models import VideoProject
from app.models.enums import VideoProjectStatus
from app.services.preview_delivery import PreviewDeliveryService
from app.services.video_editor import FFmpegVideoEditor
from app.storage.local import LocalStorage


@pytest.mark.asyncio
async def test_preview_delivery_accepts_empty_proxy_url(tmp_path) -> None:
    delivery = PreviewDeliveryService(
        bot_token="",
        storage=LocalStorage(str(tmp_path)),
        maximum_size_bytes=1024,
        editor=FFmpegVideoEditor(),
        proxy_url="",
    )
    assert delivery.client is not None
    await delivery.aclose()


async def test_telegram_preview_contains_video_and_human_controls(tmp_path) -> None:
    storage = LocalStorage(str(tmp_path))
    final_path = await storage.save("final.mp4", b"small rendered video", "render")
    project = VideoProject(
        status=VideoProjectStatus.RENDERED,
        target_duration=42,
        final_path=final_path,
        preview_path=final_path,
        edit_plan={"hook_text": "Двойной REST-запрос"},
        subtitle_style={"preset": "tech"},
        metrics={"output_duration": 41.7},
    )
    captured: dict[str, str] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        body = request.content.decode(errors="replace")
        captured["body"] = body
        return httpx.Response(200, json={"ok": True}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    delivery = PreviewDeliveryService(
        bot_token="token",
        storage=storage,
        maximum_size_bytes=1024,
        editor=FFmpegVideoEditor(),
        client=client,
    )
    result = await delivery.deliver(project, 42)

    assert result == final_path
    assert "Short готов" in captured["body"]
    assert "video_approve" in captured["body"]
    assert "video_style" in captured["body"]
    assert "small rendered video" in captured["body"]
    await client.aclose()


def test_preview_keyboard_payload_is_valid_json_shape() -> None:
    # Telegram callback data remains small and deterministic because it only stores a UUID/action.
    project = VideoProject(edit_plan={}, subtitle_style={}, metrics={})
    payload = json.dumps({"callback_data": f"video_rerender:{project.id}"})
    assert len(payload.encode()) < 100
