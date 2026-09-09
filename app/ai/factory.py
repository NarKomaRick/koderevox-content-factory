from app.ai.base import AIProvider
from app.ai.mock import MockAIProvider
from app.ai.openai_compatible import OpenAICompatibleProvider
from app.core.config import Settings


def create_ai_provider(settings: Settings) -> AIProvider:
    if settings.ai_provider == "mock":
        return MockAIProvider()
    if settings.ai_provider == "openai_compatible":
        return OpenAICompatibleProvider(
            base_url=settings.ai_base_url,
            api_key=settings.ai_api_key,
            model=settings.ai_model,
            timeout=settings.ai_timeout_seconds,
            max_retries=settings.ai_max_retries,
            max_tokens=settings.ai_max_tokens,
        )
    raise ValueError(f"Unsupported AI_PROVIDER: {settings.ai_provider}")
