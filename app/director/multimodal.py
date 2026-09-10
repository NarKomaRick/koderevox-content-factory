"""Bounded temporal preview packets and provider-neutral visual review."""

import asyncio
import hashlib
import json
from pathlib import Path
from typing import Any, Protocol

from PIL import Image, ImageDraw

from app.director.schemas import ModelCapabilityProfile
from app.services.production_rendering import probe_json


class VisionReviewProvider(Protocol):
    capabilities: ModelCapabilityProfile

    async def review(self, packet: dict[str, Any]) -> dict[str, Any]: ...


class PreviewPacketBuilder:
    def __init__(self, render_root: Path) -> None:
        self.render_root = render_root

    async def build(
        self,
        preview_path: Path,
        *,
        timeline_summary: list[dict[str, Any]],
        voiceover_segments: list[dict[str, Any]],
        beats: list[dict[str, Any]],
        validator_timestamps: list[float] | None = None,
    ) -> dict[str, Any]:
        timestamps = self._timestamps(
            preview_path, beats, timeline_summary, validator_timestamps or []
        )
        frame_dir = (
            self.render_root
            / "review"
            / hashlib.sha256(str(preview_path).encode()).hexdigest()[:16]
        )
        await asyncio.to_thread(frame_dir.mkdir, parents=True, exist_ok=True)
        frames = await self._extract(preview_path, timestamps, frame_dir)
        contact_sheet = (
            await asyncio.to_thread(self._contact_sheet, frames, frame_dir / "contact-sheet.jpg")
            if frames
            else None
        )
        digest = (
            hashlib.sha256(await asyncio.to_thread(preview_path.read_bytes)).hexdigest()
            if await asyncio.to_thread(preview_path.is_file)
            else ""
        )
        return {
            "preview_hash": digest,
            "frames": [
                {"timestamp": timestamp, "ref": f"frame-{index}"}
                for index, (timestamp, _) in enumerate(frames)
            ],
            "contact_sheet_ref": "contact-sheet" if contact_sheet else None,
            "timeline_summary": timeline_summary[:100],
            "voiceover_segments": voiceover_segments[:100],
            "beats": beats[:100],
            "output_profile": await self._profile(preview_path),
            "status": "ready" if frames else "not_tested",
        }

    @staticmethod
    def _timestamps(
        path: Path,
        beats: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        validator: list[float],
    ) -> list[float]:
        values = [float(item.get("start", 0)) for item in beats]
        values.extend(float(item) for item in validator)
        for item in timeline:
            if item.get("track") in {"graphics", "text", "broll", "video_base"}:
                values.extend(
                    [
                        float(item.get("start", 0)),
                        (float(item.get("start", 0)) + float(item.get("end", 0))) / 2,
                    ]
                )
        return sorted({round(value, 2) for value in values if value >= 0})[:24]

    async def _extract(
        self, path: Path, timestamps: list[float], directory: Path
    ) -> list[tuple[float, Path]]:
        result: list[tuple[float, Path]] = []
        for index, timestamp in enumerate(timestamps):
            destination = directory / f"frame-{index:02d}.jpg"
            process = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-ss",
                str(timestamp),
                "-i",
                str(path),
                "-frames:v",
                "1",
                str(destination),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
            if process.returncode == 0 and destination.is_file():
                result.append((timestamp, destination))
            elif process.returncode and b"not found" not in stderr.lower():
                continue
        return result

    @staticmethod
    def _contact_sheet(frames: list[tuple[float, Path]], destination: Path) -> Path:
        thumbnails: list[tuple[float, Image.Image]] = []
        for timestamp, path in frames:
            with Image.open(path) as opened:
                image = opened.convert("RGB")
                image.thumbnail((320, 320))
                thumbnails.append((timestamp, image.copy()))
        if not thumbnails:
            return destination
        columns = min(4, len(thumbnails))
        rows = (len(thumbnails) + columns - 1) // columns
        sheet = Image.new("RGB", (columns * 320, rows * 350), "#10141b")
        draw = ImageDraw.Draw(sheet)
        for index, (timestamp, image) in enumerate(thumbnails):
            x, y = (index % columns) * 320, (index // columns) * 350
            sheet.paste(image, (x, y))
            draw.text((x + 10, y + 325), f"{timestamp:.2f}s", fill="white")
        destination.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(destination, "JPEG", quality=88)
        return destination

    @staticmethod
    async def _profile(path: Path) -> dict[str, Any]:
        try:
            data = await probe_json(path)
        except (FileNotFoundError, OSError, RuntimeError, ValueError):
            return {}
        video: dict[str, Any] = next(
            (item for item in data.get("streams", []) if item.get("codec_type") == "video"), {}
        )
        return {
            key: video.get(key)
            for key in ("codec_name", "width", "height", "pix_fmt", "r_frame_rate")
        }


class PreviewReviewCache:
    def __init__(self) -> None:
        self._values: dict[tuple[str, str, str], dict[str, Any]] = {}

    def get(self, preview_hash: str, analysis_version: str, model: str) -> dict[str, Any] | None:
        return self._values.get((preview_hash, analysis_version, model))

    def put(
        self, preview_hash: str, analysis_version: str, model: str, result: dict[str, Any]
    ) -> None:
        if preview_hash:
            self._values[(preview_hash, analysis_version, model)] = json.loads(json.dumps(result))


class MetadataPreviewReviewer:
    """Text-only fallback: preserves the workflow when no vision model is available."""

    capabilities = ModelCapabilityProfile(supports_json_schema=True, max_context=8192)

    async def review(self, packet: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": packet.get("status", "not_tested"),
            "visual_review_available": False,
            "problems": [],
            "reason": "No vision provider configured; review used timeline and metadata critics.",
        }
