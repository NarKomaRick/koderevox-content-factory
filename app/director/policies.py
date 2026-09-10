"""Runtime policy and structured errors for untrusted Director model output."""

from dataclasses import dataclass
from typing import Any

from app.core.config import Settings


class DirectorToolError(ValueError):
    def __init__(self, code: str, message: str, *, recoverable: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.recoverable = recoverable

    def as_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "recoverable": self.recoverable}


@dataclass(frozen=True)
class DirectorLimits:
    max_steps: int
    max_llm_calls: int
    max_preview_renders: int
    max_critic_iterations: int
    max_external_assets: int
    max_external_bytes: int
    allow_web_assets: bool

    @classmethod
    def from_settings(cls, settings: Settings) -> "DirectorLimits":
        return cls(
            max_steps=settings.director_max_steps,
            max_llm_calls=settings.director_max_llm_calls,
            max_preview_renders=settings.director_max_preview_renders,
            max_critic_iterations=settings.director_max_critic_iterations,
            max_external_assets=settings.director_max_external_assets,
            max_external_bytes=settings.director_max_external_bytes,
            allow_web_assets=settings.director_allow_web_assets,
        )
