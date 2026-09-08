import asyncio
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import structlog

from app.schemas.video import EditClip
from app.services.media import MediaProcessingError

logger = structlog.get_logger()
SILENCE_START = re.compile(r"silence_start:\s*([0-9.]+)")
SILENCE_END = re.compile(r"silence_end:\s*([0-9.]+)")


@dataclass(frozen=True)
class TimeRange:
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


class PauseDetector(Protocol):
    async def detect(self, source: Path) -> list[TimeRange]: ...


class FFmpegPauseDetector:
    def __init__(self, min_duration: float = 0.65, noise_db: float = -35) -> None:
        self.min_duration = min_duration
        self.noise_db = noise_db

    async def detect(self, source: Path) -> list[TimeRange]:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(source),
            "-af",
            f"silencedetect=noise={self.noise_db}dB:d={self.min_duration}",
            "-f",
            "null",
            "-",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise MediaProcessingError("FFmpeg silence detection failed")
        pauses = self.parse(stderr.decode(errors="replace"))
        await logger.ainfo("pauses_detected", count=len(pauses), path=str(source))
        return pauses

    @staticmethod
    def parse(stderr: str) -> list[TimeRange]:
        pauses: list[TimeRange] = []
        pending: float | None = None
        for line in stderr.splitlines():
            start_match = SILENCE_START.search(line)
            if start_match:
                pending = float(start_match.group(1))
            end_match = SILENCE_END.search(line)
            if end_match and pending is not None:
                end = float(end_match.group(1))
                if end > pending:
                    pauses.append(TimeRange(pending, end))
                pending = None
        return pauses


def clips_without_long_pauses(
    clips: list[EditClip],
    pauses: list[TimeRange],
    *,
    keep_padding: float,
    minimum_clip: float = 0.3,
    minimum_pause: float = 0.65,
) -> list[TimeRange]:
    """Subtract only the interior of detected long pauses from selected clips."""
    result: list[TimeRange] = []
    for clip in clips:
        parts = [TimeRange(clip.source_start, clip.source_end)]
        for pause in pauses:
            if pause.duration < minimum_pause:
                continue
            removal_start = max(clip.source_start, pause.start + keep_padding)
            removal_end = min(clip.source_end, pause.end - keep_padding)
            if removal_end <= removal_start:
                continue
            next_parts: list[TimeRange] = []
            for part in parts:
                if removal_start >= part.end or removal_end <= part.start:
                    next_parts.append(part)
                    continue
                if removal_start - part.start >= minimum_clip:
                    next_parts.append(TimeRange(part.start, removal_start))
                if part.end - removal_end >= minimum_clip:
                    next_parts.append(TimeRange(removal_end, part.end))
            parts = next_parts
        result.extend(parts)
    return result
