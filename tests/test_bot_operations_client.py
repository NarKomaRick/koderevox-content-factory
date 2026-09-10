import httpx

from app.bot.api_client import BackendClient


async def test_operations_status_sends_telegram_actor_header() -> None:
    captured: dict[str, str | None] = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["actor"] = request.headers.get("X-Actor-Telegram-Id")
        return httpx.Response(200, json={"failed": 0}, request=request)

    backend = BackendClient("http://api")
    await backend.close()
    backend.client = httpx.AsyncClient(
        base_url="http://api", transport=httpx.MockTransport(handler)
    )
    try:
        await backend.operations_status(telegram_user_id=1044804334)
    finally:
        await backend.close()

    assert captured["actor"] == "1044804334"
