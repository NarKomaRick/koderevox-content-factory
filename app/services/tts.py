"""Optional local text-to-speech providers for capability tests."""

from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.services.errors import ProcessingError


@dataclass(frozen=True)
class TTSResult:
    path: Path
    duration: float
    sample_rate: int
    language: str
    provider: str
    voice: str


class TextToSpeechProvider(Protocol):
    async def synthesize(
        self,
        text: str,
        output_path: Path,
        voice: str | None = None,
        language: str | None = None,
    ) -> TTSResult: ...


class EspeakTTSProvider:
    """Small offline provider intended for smoke/capability testing, not production."""

    def __init__(
        self,
        executable: str = "espeak-ng",
        default_language: str = "ru",
        rate: int | None = None,
        volume: int | None = None,
    ) -> None:
        self.executable = executable
        self.default_language = default_language
        self.rate = rate
        self.volume = volume

    async def synthesize(
        self,
        text: str,
        output_path: Path,
        voice: str | None = None,
        language: str | None = None,
    ) -> TTSResult:
        text = text.strip()
        if not text:
            raise ValueError("TTS text must not be empty")
        if shutil.which(self.executable) is None:
            raise ProcessingError(
                f"TTS executable not found: {self.executable}. Install espeak-ng or disable TTS."
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        lang = language or self.default_language
        selected_voice = voice or lang
        args = [self.executable, "-v", selected_voice]
        if self.rate is not None:
            args.extend(["-s", str(self.rate)])
        if self.volume is not None:
            args.extend(["-a", str(self.volume)])
        args.extend(["-w", str(output_path), text])
        process = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise ProcessingError(
                f"espeak-ng failed ({process.returncode}): "
                f"{stderr.decode(errors='replace').strip()}"
            )
        if not output_path.is_file() or output_path.stat().st_size == 0:  # noqa: ASYNC240
            raise ProcessingError("TTS produced no audio output")
        probe = await self._probe(output_path)
        streams = [item for item in probe.get("streams", []) if item.get("codec_type") == "audio"]
        if not streams:
            raise ProcessingError("TTS output has no audio stream")
        duration = float(probe.get("format", {}).get("duration") or 0)
        sample_rate = int(streams[0].get("sample_rate") or 0)
        if duration <= 0 or sample_rate <= 0:
            raise ProcessingError("TTS output has invalid duration or sample rate")
        return TTSResult(output_path, duration, sample_rate, lang, "espeak", selected_voice)

    async def _probe(self, path: Path) -> dict[str, Any]:
        process = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-of",
            "json",
            "-show_streams",
            "-show_format",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode:
            raise ProcessingError(f"ffprobe failed: {stderr.decode(errors='replace').strip()}")
        return json.loads(stdout)
