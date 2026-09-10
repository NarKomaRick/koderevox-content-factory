from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TopicCandidate:
    pillar: str
    topic: str
    reason: str
    priority: float


class FakeStrategist:
    """Deterministic topic suggestions; research remains Producer responsibility."""

    topics = {
        "AI": "Практический приём для локальных AI-инструментов",
        "Backend": "Backend-ошибка, которую легко обнаружить заранее",
        "Mobile": "Мобильная функция без лишней сложности",
        "Automation": "Автоматизация повторяющейся инженерной задачи",
    }

    def suggest(
        self, pillars: list[str], recent_topics: set[str] | None = None
    ) -> list[TopicCandidate]:
        recent_topics = recent_topics or set()
        candidates = []
        for index, pillar in enumerate(pillars):
            topic = self.topics.get(pillar, f"Полезный разбор по теме {pillar}")
            if topic in recent_topics:
                continue
            candidates.append(
                TopicCandidate(pillar, topic, "fits the selected content pillar", 1 - index * 0.05)
            )
        return candidates
