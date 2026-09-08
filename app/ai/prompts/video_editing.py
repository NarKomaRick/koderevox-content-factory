import json
from typing import Any

from app.models import ContentDraft, SourceItem
from app.schemas.video import EditPlan, VideoConcept


def _source_context(source: SourceItem, draft: ContentDraft | None = None) -> str:
    intelligence = source.content_analysis or {}
    parts = [
        f"Topic: {source.topic or ''}",
        f"Summary: {source.summary or ''}",
        "FACTS FROM SOURCE:\n" + "\n".join(map(str, intelligence.get("source_facts", []))),
        "Transcript (the only source of spoken speech):\n" + (source.transcript or ""),
    ]
    if draft is not None:
        parts.append(f"Editorial draft for intent only (not spoken truth):\n{draft.script}")
    return "\n\n".join(parts)


def build_video_concepts_prompt(source: SourceItem, draft: ContentDraft | None = None) -> str:
    return f"""Create exactly three genuinely different short-video edit concepts.
Use only the supplied transcript and source facts. Do not invent a spoken phrase, fact, result,
number, client, cause or consequence. The hook field is an on-screen editorial overlay and must
not be presented as a quote unless it occurs in the transcript. Prefer a coherent human story over
hyperactive editing. Suggest SCREEN_FIT for screen recordings and CENTER_CROP or FIT_BLUR
for a speaker.

{_source_context(source, draft)}
"""


def build_edit_plan_prompt(
    source: SourceItem,
    concept: VideoConcept,
    *,
    current_plan: EditPlan | None = None,
    instruction: str | None = None,
    validation_error: str | None = None,
) -> str:
    indexed_segments: list[dict[str, Any]] = []
    for index, segment in enumerate(source.transcript_segments):
        indexed_segments.append(
            {
                "id": index,
                "start": segment.get("start"),
                "end": segment.get("end"),
                "text": segment.get("text"),
            }
        )
    existing = current_plan.model_dump(mode="json") if current_plan else None
    return f"""Create a deterministic EditPlan for the selected concept.

STRICT RULES:
- Every clip must reference one or more IDs from TRANSCRIPT_SEGMENTS.
- source_start/source_end must lie inside the time span of those real segments.
- Preserve source chronology and do not overlap source clips.
- Never manufacture spoken content. Editing may only select or remove existing speech.
- Emphasis text must be an exact phrase that exists in selected transcript text.
- Do not remove natural micro-pauses; choose coherent sentence boundaries.
- hook_text is a short overlay, not a replacement for spoken subtitles.

SOURCE_DURATION: {source.duration_seconds}
CONCEPT: {concept.model_dump_json()}
TRANSCRIPT_SEGMENTS:
{json.dumps(indexed_segments, ensure_ascii=False)}
CURRENT_PLAN: {json.dumps(existing, ensure_ascii=False)}
USER_INSTRUCTION: {instruction or ""}
PREVIOUS_VALIDATION_ERROR: {validation_error or ""}
"""
