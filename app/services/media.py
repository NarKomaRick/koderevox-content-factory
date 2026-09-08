import asyncio
import json
from pathlib import Path
from typing import Any

import structlog

from app.services.errors import PermanentProcessingError

logger = structlog.get_logger()


class MediaProcessingError(PermanentProcessingError):
    pass


class FFmpegMediaProcessor:
    async def probe(self, source: Path) -> dict[str, Any]:
        process = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(source),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise MediaProcessingError(stderr.decode(errors="replace"))
        await logger.ainfo("media_probed", path=str(source))
        return json.loads(stdout)

    async def extract_audio(self, source: Path, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-y",
            "-i",
            str(source),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            str(destination),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            raise MediaProcessingError(stderr.decode(errors="replace"))
        await logger.ainfo("audio_extracted", source=str(source), destination=str(destination))
        return destination

    async def normalize_audio(self, source: Path, destination: Path) -> Path:
        return await self.extract_audio(source, destination)

    @staticmethod
    def useful_metadata(probe: dict[str, Any]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        format_data = probe.get("format", {})
        if format_data.get("duration"):
            result["duration_seconds"] = float(format_data["duration"])
        for stream in probe.get("streams", []):
            if stream.get("codec_type") == "video":
                result["width"] = stream.get("width")
                result["height"] = stream.get("height")
                frame_rate = stream.get("avg_frame_rate")
                if frame_rate and frame_rate != "0/0":
                    numerator, denominator = frame_rate.split("/", maxsplit=1)
                    if float(denominator):
                        result["fps"] = round(float(numerator) / float(denominator), 3)
                result["video_codec"] = stream.get("codec_name")
            elif stream.get("codec_type") == "audio":
                result["audio_codec"] = stream.get("codec_name")
                result["sample_rate"] = stream.get("sample_rate")
        return result
