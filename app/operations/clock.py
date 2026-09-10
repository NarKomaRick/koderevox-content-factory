from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FakeClock:
    def __init__(self, value: datetime) -> None:
        self.value = value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)

    def now(self) -> datetime:
        return self.value

    def advance(self, **kwargs: float) -> datetime:
        self.value += timedelta(**kwargs)
        return self.value
