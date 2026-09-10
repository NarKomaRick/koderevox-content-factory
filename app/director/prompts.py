"""Compact prompts for structured Director turns (no FFmpeg instructions)."""

import json
from typing import Any

DIRECTOR_SYSTEM_PROMPT = """You are the video director and editor of Koderevox AI Content Factory.
Choose visuals that match the spoken meaning, use exact asset IDs and exact clip ranges, preserve
voiceover as the immutable audio master, respect the supplied output profile and safe zones, and
request validation/preview before finalizing. You have no shell, filesystem, URL, or FFmpeg access.
Use only registered tools. Never invent an asset. Prefer a small number of meaningful changes over
random effects. If a tool returns a recoverable error, correct the arguments and retry."""


def build_director_user_prompt(
    context: dict[str, Any], tools: list[dict[str, Any]], instruction: str
) -> str:
    bounded = json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    tool_names = [item["function"]["name"] for item in tools]
    return (
        f"CURRENT_INSTRUCTION:\n{instruction[:10000]}\n\n"
        f"AVAILABLE_TOOLS:\n{json.dumps(tool_names)}\n\n"
        f"BOUNDED_CONTEXT_JSON:\n{bounded}"
    )
