"""Explainable candidate ranking for Director choice, never an automatic top-one edit."""

from difflib import SequenceMatcher
from typing import Any


class VisualCandidateRanker:
    PRIORITY = {
        "video": 1.0,
        "screen_recording": 0.95,
        "screenshot": 0.9,
        "image": 0.75,
    }

    def rank(
        self, assets: list[dict[str, Any]], meaning: str, *, limit: int = 5
    ) -> list[dict[str, Any]]:
        query = self._tokens(meaning)
        candidates: list[dict[str, Any]] = []
        for asset in assets:
            text = " ".join(
                [
                    str(asset.get("title", "")),
                    str(asset.get("description", "")),
                    " ".join(asset.get("tags", [])),
                ]
            )
            tokens = self._tokens(text)
            lexical = len(query & tokens) / max(1, len(query))
            similarity = SequenceMatcher(
                None, " ".join(sorted(query)), " ".join(sorted(tokens))
            ).ratio()
            source = str(asset.get("source", "user"))
            score = (
                0.55 * lexical
                + 0.25 * similarity
                + 0.2 * self.PRIORITY.get(str(asset.get("type")), 0.5)
            )
            candidates.append(
                {
                    "asset_id": asset.get("id"),
                    "score": round(min(1.0, score), 4),
                    "reason": "semantic metadata match with source/type guidance",
                    "source": source,
                    "type": asset.get("type"),
                    "alternatives_allowed": True,
                }
            )
        candidates.sort(key=lambda item: (-float(item["score"]), str(item["asset_id"])))
        return candidates[: max(1, min(limit, 5))]

    @staticmethod
    def _tokens(value: str) -> set[str]:
        return {token.casefold() for token in value.replace("_", " ").split() if len(token) > 2}
