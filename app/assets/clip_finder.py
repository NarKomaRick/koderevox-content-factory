"""Small deterministic clip finder with an upgrade path to embeddings/scene models."""

import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from app.models import VisualAsset


@dataclass(frozen=True)
class ClipCandidate:
    asset_id: str
    start: float
    end: float
    description: str
    score: float
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "start": self.start,
            "end": self.end,
            "description": self.description,
            "score": self.score,
            "reason": self.reason,
        }


class ClipFinder:
    """Ranks cached scene segments; full-video fallback remains bounded and safe."""

    def find(
        self,
        asset: VisualAsset,
        description: str,
        *,
        preferred_duration: float = 4.0,
        limit: int = 5,
    ) -> list[ClipCandidate]:
        query = self._tokens(description)
        analysis = asset.analysis if isinstance(asset.analysis, dict) else {}
        raw_segments = analysis.get("scene_segments", [])
        segments = raw_segments if isinstance(raw_segments, list) else []
        if not segments:
            duration = float(asset.duration or preferred_duration)
            end = min(duration, max(0.5, preferred_duration))
            return [
                ClipCandidate(
                    str(asset.id),
                    0.0,
                    end,
                    asset.description or asset.filename,
                    0.2,
                    "asset-level fallback",
                )
            ]
        candidates: list[ClipCandidate] = []
        for segment in segments:
            if not isinstance(segment, dict):
                continue
            start, end = float(segment.get("start", 0)), float(segment.get("end", 0))
            if end <= start:
                continue
            text = str(segment.get("description", ""))
            tags = " ".join(str(value) for value in segment.get("visual_tags", []))
            score = self._score(
                query, self._tokens(f"{text} {tags} {asset.title} {asset.description}")
            )
            selected_end = min(end, start + max(0.5, preferred_duration))
            candidates.append(
                ClipCandidate(
                    str(asset.id), start, selected_end, text, score, "scene metadata match"
                )
            )
        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates[:limit]

    @staticmethod
    def _tokens(text: str) -> str:
        return " ".join(re.findall(r"[\w+#.-]+", text.casefold(), flags=re.UNICODE))

    @staticmethod
    def _score(query: str, text: str) -> float:
        if not query or not text:
            return 0.1
        query_words, text_words = set(query.split()), set(text.split())
        lexical = len(query_words & text_words) / max(1, len(query_words))
        fuzzy = SequenceMatcher(None, query, text).ratio()
        return round(min(1.0, lexical * 0.7 + fuzzy * 0.3), 4)
