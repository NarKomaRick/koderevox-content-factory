from typing import Any


def quality_scores(*, visual_count: int, issue_count: int, gap_count: int) -> dict[str, float]:
    relevance = min(10.0, 5.0 + min(visual_count, 6) * 0.7)
    pacing = max(0.0, 9.0 - gap_count * 1.25)
    readability = max(0.0, 10.0 - issue_count * 2.0)
    overall = round((relevance + pacing + readability) / 3, 1)
    return {
        "overall_score": overall,
        "pacing": round(pacing, 1),
        "readability": round(readability, 1),
        "visual_relevance": round(relevance, 1),
    }


def merge_quality(base: dict[str, Any], scores: dict[str, float]) -> dict[str, Any]:
    return {**base, **scores}
