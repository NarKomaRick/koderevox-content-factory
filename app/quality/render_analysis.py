"""Render inspection accepts only application-resolved paths."""

import asyncio
import json
from pathlib import Path
from typing import Any


async def probe_render(path: Path) -> dict[str, Any]:
    process = await asyncio.create_subprocess_exec(
        "ffprobe",
        "-v",
        "error",
        "-show_streams",
        "-show_format",
        "-of",
        "json",
        str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await process.communicate()
    if process.returncode:
        raise ValueError(f"ffprobe failed: {stderr.decode(errors='replace')[-500:]}")
    return json.loads(stdout)
