import asyncio
import base64
import json
import time
from pathlib import Path
from typing import Protocol

import httpx
import structlog
from pydantic import ValidationError

from app.models import Project, VisualAsset
from app.schemas.assets import AssetIntelligence
from app.services.errors import InvalidStateError

logger = structlog.get_logger()


class VisionProvider(Protocol):
    external: bool

    async def analyze(
        self, image_path: Path, *, context: str, extracted_text: str
    ) -> AssetIntelligence: ...


class DisabledVisionProvider:
    external = False

    async def analyze(
        self, image_path: Path, *, context: str, extracted_text: str
    ) -> AssetIntelligence:
        return AssetIntelligence(summary=context, visible_code=extracted_text or None)


class OpenAICompatibleVisionProvider:
    external = True

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 120,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.model = model
        self._owns_client = client is None
        self.client = client or httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def analyze(
        self, image_path: Path, *, context: str, extracted_text: str
    ) -> AssetIntelligence:
        started = time.monotonic()
        mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
        raw = await asyncio.to_thread(image_path.read_bytes)
        encoded = base64.b64encode(raw).decode("ascii")
        prompt = (
            "Analyze this visual asset for conservative technical-video B-roll retrieval. "
            "Never infer hidden code or private data. Return JSON matching this schema: "
            f"{json.dumps(AssetIntelligence.model_json_schema())}. Context: {context}. "
            f"Local OCR (may be empty): {extracted_text[:12000]}"
        )
        response = await self.client.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={
                "model": self.model,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {"url": f"data:{mime};base64,{encoded}"},
                            },
                        ],
                    }
                ],
                "temperature": 0.1,
                "response_format": {"type": "json_object"},
            },
        )
        response.raise_for_status()
        try:
            content = response.json()["choices"][0]["message"]["content"]
            result = AssetIntelligence.model_validate_json(content)
        except (KeyError, TypeError, ValidationError) as exc:
            raise InvalidStateError("Vision provider returned invalid structured data") from exc
        await logger.ainfo(
            "vision_completed",
            duration=round(time.monotonic() - started, 3),
            model=self.model,
        )
        return result


class PrivacyAwareVisionService:
    def __init__(self, provider: VisionProvider) -> None:
        self.provider = provider

    async def analyze(
        self, asset: VisualAsset, project: Project, image_path: Path
    ) -> AssetIntelligence:
        if self.provider.external and not project.allow_external_vision:
            raise InvalidStateError("External vision is disabled for this project")
        return await self.provider.analyze(
            image_path,
            context=". ".join(filter(None, [asset.title, asset.description])),
            extracted_text=asset.extracted_text or "",
        )
