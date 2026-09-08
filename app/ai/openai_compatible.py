import json
import time
from typing import Any, TypeVar

import httpx
import structlog
from pydantic import BaseModel, ValidationError

OutputT = TypeVar("OutputT", bound=BaseModel)
logger = structlog.get_logger()


class AIProviderError(RuntimeError):
    pass


class OpenAICompatibleProvider:
    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 120,
        max_retries: int = 2,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self.max_retries = max_retries
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        response_model: type[OutputT],
    ) -> OutputT:
        error: Exception | None = None
        feedback = ""
        for attempt in range(self.max_retries + 1):
            started = time.monotonic()
            response_format: dict[str, Any]
            if attempt == 0:
                response_format = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": response_model.__name__,
                        "strict": True,
                        "schema": response_model.model_json_schema(),
                    },
                }
            else:
                response_format = {"type": "json_object"}
            payload: dict[str, Any] = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt + feedback},
                ],
                "temperature": 0.7,
                "response_format": response_format,
            }
            try:
                response = await self.client.post(
                    f"{self.base_url}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json=payload,
                )
                response.raise_for_status()
                content = response.json()["choices"][0]["message"]["content"]
                result = response_model.model_validate_json(content)
                await logger.ainfo(
                    "ai_generation_completed",
                    provider="openai_compatible",
                    model=self.model,
                    attempt=attempt + 1,
                    duration_ms=round((time.monotonic() - started) * 1000),
                )
                return result
            except (
                httpx.HTTPError,
                KeyError,
                TypeError,
                json.JSONDecodeError,
                ValidationError,
            ) as exc:
                error = exc
                await logger.awarning(
                    "ai_generation_failed",
                    provider="openai_compatible",
                    model=self.model,
                    attempt=attempt + 1,
                    error_type=type(exc).__name__,
                )
                feedback = (
                    "\n\nThe previous response was invalid. Return ONLY valid JSON "
                    "matching this JSON schema:\n"
                    f"{json.dumps(response_model.model_json_schema(), ensure_ascii=False)}"
                )
        raise AIProviderError(f"AI returned no valid structured response: {error}")
