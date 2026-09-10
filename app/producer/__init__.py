"""Phase 8 autonomous content producer.

The package is deliberately provider-neutral.  It owns content decisions and
hands a compact, provenance-aware package to the existing Director.
"""

from app.producer.domain import (
    AssetPlan,
    ContentAngle,
    ContentBrief,
    DirectorHandoffPackage,
    FactConflict,
    ProducerIntent,
    ProducerReport,
    ProducerStatus,
    ResearchFact,
    ResearchPlan,
    ScriptOutline,
    ScriptReview,
    ScriptSegment,
    TopicCandidate,
)

__all__ = [
    "AssetPlan",
    "ContentAngle",
    "ContentBrief",
    "DirectorHandoffPackage",
    "FactConflict",
    "ProducerIntent",
    "ProducerReport",
    "ProducerStatus",
    "ResearchFact",
    "ResearchPlan",
    "ScriptOutline",
    "ScriptReview",
    "ScriptSegment",
    "TopicCandidate",
]
