import random
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.services.publishing_errors import PublishingError


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    retry_at: datetime | None = None


class RetryPolicy:
    def __init__(
        self,
        *,
        max_attempts: int = 5,
        delays_seconds: list[int] | None = None,
        jitter_ratio: float = 0.15,
        random_source: random.Random | None = None,
    ) -> None:
        self.max_attempts = max_attempts
        self.delays = delays_seconds or [60, 300, 900, 3600]
        self.jitter_ratio = jitter_ratio
        self.random = random_source or random.Random()

    def decide(
        self, attempt_number: int, error: PublishingError, *, now: datetime | None = None
    ) -> RetryDecision:
        if not error.retryable or attempt_number >= self.max_attempts:
            return RetryDecision(False)
        base = self.delays[min(attempt_number - 1, len(self.delays) - 1)]
        jitter = self.random.uniform(-self.jitter_ratio, self.jitter_ratio)
        retry_at = (now or datetime.now(UTC)) + timedelta(seconds=max(1, base * (1 + jitter)))
        return RetryDecision(True, retry_at)
