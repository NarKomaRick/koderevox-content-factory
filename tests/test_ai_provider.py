import json

import httpx

from app.ai.openai_compatible import OpenAICompatibleProvider
from app.schemas.ai import ContentAngleBatch


async def test_structured_provider_retries_invalid_json() -> None:
    calls = 0
    formats: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        formats.append(json.loads(request.content)["response_format"]["type"])
        if calls == 1:
            content = "not-json"
        else:
            content = json.dumps(
                {
                    "angles": [
                        {
                            "title": f"Title {index}",
                            "hook": f"Hook {index}",
                            "angle": f"Distinct angle {index}",
                            "description": f"Description {index}",
                            "format": "short_video",
                            "estimated_duration": 30 + index,
                            "content_pillar": "education",
                            "target_audience": "Developers",
                            "score": 8,
                        }
                        for index in range(3)
                    ]
                }
            )
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": content}}]},
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        base_url="http://llm.local/v1",
        api_key="secret",
        model="test",
        max_retries=1,
        client=client,
    )

    result = await provider.generate_structured(
        system_prompt="system", user_prompt="user", response_model=ContentAngleBatch
    )

    assert calls == 2
    assert formats == ["json_schema", "json_object"]
    assert len(result.angles) == 3
    await client.aclose()


async def test_provider_sends_json_schema_without_exposing_key_in_body() -> None:
    captured: dict = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        content = {
            "angles": [
                {
                    "title": f"Title {i}",
                    "hook": f"Hook {i}",
                    "angle": f"Angle {i}",
                    "description": f"Description {i}",
                    "format": "short_video",
                    "estimated_duration": 30,
                    "content_pillar": "case",
                    "target_audience": "Business",
                    "score": 7,
                }
                for i in range(3)
            ]
        }
        return httpx.Response(
            200,
            json={"choices": [{"message": {"content": json.dumps(content)}}]},
            request=request,
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    provider = OpenAICompatibleProvider(
        base_url="http://localhost:1234/v1",
        api_key="super-secret",
        model="local",
        client=client,
    )
    await provider.generate_structured(
        system_prompt="system", user_prompt="user", response_model=ContentAngleBatch
    )

    assert captured["response_format"]["type"] == "json_schema"
    assert captured["max_tokens"] == 1536
    assert "super-secret" not in json.dumps(captured)
    await client.aclose()
