import asyncio
import json
import re
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any

import structlog
from PIL import Image, ImageDraw, ImageFont
from PIL.ImageFont import FreeTypeFont
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.editing.graphics import GraphicsRenderer
from app.models import (
    ProductionProject,
    Project,
    ScriptVersion,
    TimelineRevision,
    VideoProject,
    VisualAsset,
    VoiceoverTrack,
)
from app.models.enums import (
    AssetType,
    ProductionStatus,
    SubtitlePreset,
    TimelineTrack,
    VideoProjectStatus,
)
from app.schemas.production import ProductionTimeline, TimelineItem
from app.services.audio import AudioProcessor
from app.services.errors import InvalidStateError, NotFoundError
from app.services.graphics import CodeCardRenderer
from app.services.media import MediaProcessingError
from app.services.pause import TimeRange
from app.services.production_timeline import render_profile
from app.services.subtitles import SubtitleService
from app.services.video_editor import FFmpegVideoEditor
from app.storage.base import Storage

logger = structlog.get_logger()


class ProductionRenderService:
    """Renders a saved timeline with VoiceoverTrack as immutable duration/audio master."""

    def __init__(self, session: AsyncSession, storage: Storage, settings: Settings) -> None:
        self.session = session
        self.storage = storage
        self.settings = settings
        self.subtitles = SubtitleService()
        self.validator = FFmpegVideoEditor(font_path=settings.video_font_path)

    async def render(
        self, production_project_id: uuid.UUID, *, profile_name: str = "preview"
    ) -> VideoProject:
        production = await self.session.get(ProductionProject, production_project_id)
        if production is None or not production.active_timeline_revision_id:
            raise InvalidStateError("Create a timeline before rendering")
        revision = await self.session.get(TimelineRevision, production.active_timeline_revision_id)
        if revision is None:
            raise NotFoundError("TimelineRevision not found")
        timeline = ProductionTimeline.model_validate(revision.timeline_json)
        voiceover = await self.session.get(VoiceoverTrack, timeline.voiceover_track_id)
        brand = await self.session.get(Project, production.project_id)
        if voiceover is None or brand is None:
            raise NotFoundError("Voiceover or brand project not found")
        audio_path = self.storage.resolve(voiceover.processed_path)
        if not audio_path.is_file():
            raise InvalidStateError("Processed voiceover file does not exist")
        profile = render_profile(self.settings, profile_name)
        root = Path(self.settings.render_temp_root)
        await asyncio.to_thread(root.mkdir, parents=True, exist_ok=True)
        workspace = Path(tempfile.mkdtemp(prefix=f"production-{production.id}-", dir=root))
        try:
            subtitle_path = await self._subtitles(
                workspace, voiceover, production, brand, profile.width, profile.height
            )
            prepared = await self._prepare_visuals(workspace, timeline)
            output = workspace / f"{profile.name}.mp4"
            command = self._command(audio_path, output, subtitle_path, timeline, prepared, profile)
            await self._run(command)
            result = await self.validator.validate_output(
                output, expected_width=profile.width, expected_height=profile.height
            )
            if abs(result.duration - voiceover.duration) > 0.35:
                raise MediaProcessingError("Rendered duration does not match VoiceoverTrack")
            stored = await self.storage.save_file(
                f"production-{production.id}-{revision.revision_number}-{profile.name}.mp4",
                output,
                "preview" if profile.name == "preview" else "render",
            )
            video = await self._video_project(production, voiceover)
            video.target_duration = voiceover.duration
            video.render_settings = profile.model_dump()
            video.visual_plan = timeline.model_dump(mode="json")
            video.metrics = {
                **video.metrics,
                "production_project_id": str(production.id),
                "timeline_revision": revision.revision_number,
                "audio_master": str(voiceover.id),
                "duration": result.duration,
                "profile": profile.name,
            }
            if profile.name == "preview":
                video.preview_path = stored
                video.status = VideoProjectStatus.RENDERED
                production.status = ProductionStatus.REVIEW
            else:
                video.final_path = stored
                video.status = VideoProjectStatus.APPROVED
                production.status = ProductionStatus.APPROVED
            production.active_video_project_id = video.id
            await self.session.commit()
            await self.session.refresh(video)
            return video
        finally:
            await asyncio.to_thread(shutil.rmtree, workspace, True)

    async def _video_project(
        self, production: ProductionProject, voiceover: VoiceoverTrack
    ) -> VideoProject:
        current = (
            await self.session.get(VideoProject, production.active_video_project_id)
            if production.active_video_project_id
            else None
        )
        if current:
            return current
        video = VideoProject(
            project_id=production.project_id,
            source_item_id=voiceover.source_item_id,
            format="voiceover_driven",
            status=VideoProjectStatus.RENDERING,
            target_duration=voiceover.duration,
            aspect_ratio="9:16",
            edit_plan={"mode": "voiceover_driven"},
            subtitle_style={"preset": SubtitlePreset.TECH.value},
            render_settings={},
            metrics={"production_project_id": str(production.id)},
        )
        self.session.add(video)
        await self.session.flush()
        return video

    async def _subtitles(
        self,
        workspace: Path,
        voiceover: VoiceoverTrack,
        production: ProductionProject,
        brand: Project,
        width: int,
        height: int,
    ) -> Path:
        overrides: dict[str, str] = {}
        # Correct only known aliases whose canonical spelling occurs in approved text.
        script = (
            await self.session.get(ScriptVersion, production.approved_script_version_id)
            if production.approved_script_version_id
            else None
        )
        approved = script.content if isinstance(script, ScriptVersion) else ""
        for spoken, canonical in {"рест апи": "REST API", "постгрес": "PostgreSQL"}.items():
            if canonical.casefold() in approved.casefold():
                overrides[spoken] = canonical
        cues = self.subtitles.create_cues(
            voiceover.segments,
            [TimeRange(0, voiceover.duration)],
            preset=SubtitlePreset.TECH,
            vocabulary=brand.vocabulary,
            overrides=overrides,
        )
        return self.subtitles.write_ass(
            workspace / "voiceover.ass",
            cues,
            preset=SubtitlePreset.TECH,
            width=width,
            height=height,
        )

    async def _prepare_visuals(
        self, workspace: Path, timeline: ProductionTimeline
    ) -> list[tuple[TimelineItem, Path, bool]]:
        result: list[tuple[TimelineItem, Path, bool]] = []
        for index, item in enumerate(timeline.items):
            if item.track not in {
                TimelineTrack.BROLL,
                TimelineTrack.OVERLAY,
                TimelineTrack.GRAPHICS,
                TimelineTrack.TEXT,
            }:
                continue
            if item.asset_id:
                asset = await self.session.get(VisualAsset, item.asset_id)
                if asset is None:
                    continue
                path = self.storage.resolve(asset.processed_path or asset.original_path)
                if not path.is_file():
                    continue
                if asset.type == AssetType.CODE:
                    card = workspace / f"code-{index}.png"
                    code = asset.extracted_text
                    if not code:
                        code = await asyncio.to_thread(path.read_text, errors="replace")
                    await CodeCardRenderer().render(
                        code,
                        card,
                        width=self.settings.preview_width,
                        height=self.settings.preview_height,
                    )
                    result.append((item, card, False))
                    continue
                is_video = asset.type in {AssetType.VIDEO, AssetType.SCREEN_RECORDING}
                result.append((item, path, is_video))
            elif item.metadata.get("graphic"):
                graphic = workspace / f"graphic-{index}.png"
                await GraphicsRenderer().render(
                    str(item.metadata["graphic"]),
                    item.metadata.get("content", {}),
                    graphic,
                    width=self.settings.preview_width,
                    height=self.settings.preview_height,
                    font_path=self.settings.video_font_path,
                    style=str(item.metadata.get("style", "technical")),
                )
                result.append((item, graphic, False))
            elif item.text:
                path = workspace / f"card-{index}.png"
                await asyncio.to_thread(self._draw_card, path, item.text)
                result.append((item, path, False))
        return result

    def _command(
        self,
        audio: Path,
        output: Path,
        subtitles: Path,
        timeline: ProductionTimeline,
        visuals: list[tuple[TimelineItem, Path, bool]],
        profile: Any,
    ) -> list[str]:
        inputs = [
            "-i",
            str(audio),
            "-f",
            "lavfi",
            "-i",
            f"color=c=0x0B0F14:s={profile.width}x{profile.height}:r=30:d={timeline.duration:.3f}",
        ]
        filters: list[str] = ["[1:v]setpts=PTS-STARTPTS[base]"]
        current = "base"
        for offset, (item, path, is_video) in enumerate(visuals, start=2):
            duration = item.end - item.start
            if is_video:
                inputs.extend(
                    [
                        "-ss",
                        f"{item.source_start or 0:.3f}",
                        "-t",
                        f"{duration:.3f}",
                        "-i",
                        str(path),
                    ]
                )
            else:
                inputs.extend(["-loop", "1", "-t", f"{duration:.3f}", "-i", str(path)])
            if item.layout == "picture_in_picture":
                width, height = int(profile.width * 0.62), int(profile.height * 0.42)
                x, y = "W-w-40", "H-h-300"
            else:
                width, height = profile.width, profile.height
                x, y = "0", "0"
            if item.layout == "blur_background_fit":
                filters.append(
                    f"[{offset}:v]setsar=1,split=2[bgraw{offset}][fgraw{offset}];"
                    f"[bgraw{offset}]scale={profile.width}:{profile.height}:force_original_aspect_ratio=increase,"
                    f"crop={profile.width}:{profile.height},boxblur=20:2[bg{offset}];"
                    f"[fgraw{offset}]scale={profile.width}:{profile.height}:force_original_aspect_ratio=decrease:force_divisible_by=2,"
                    f"pad={profile.width}:{profile.height}:(ow-iw)/2:(oh-ih)/2:color=0x10141b[fg{offset}];"
                    f"[bg{offset}][fg{offset}]overlay=(W-w)/2:(H-h)/2,trim=duration={duration:.3f},"
                    f"setpts=PTS-STARTPTS+{item.start:.3f}/TB[vis{offset}]"
                )
            else:
                filters.append(
                    f"[{offset}:v]setsar=1,scale={width}:{height}:"
                    "force_original_aspect_ratio=decrease:force_divisible_by=2,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x10141b,"
                    f"trim=duration={duration:.3f},setpts=PTS-STARTPTS+{item.start:.3f}/TB[vis{offset}]"
                )
            next_label = f"v{offset}"
            filters.append(
                f"[{current}][vis{offset}]overlay=x={x}:y={y}:eof_action=pass:shortest=0:"
                f"enable='between(t,{item.start:.3f},{item.end:.3f})'[{next_label}]"
            )
            current = next_label
        subtitle_path = (
            str(subtitles.resolve()).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")
        )
        filters.append(f"[{current}]ass=filename='{subtitle_path}',fps=30,format=yuv420p[vout]")
        audio_filter = AudioProcessor(
            normalization_enabled=self.settings.audio_normalization_enabled,
            noise_reduction_enabled=self.settings.audio_noise_reduction_enabled,
        ).ffmpeg_filter()
        filters.append(f"[0:a]{audio_filter},atrim=duration={timeline.duration:.3f}[aout]")
        return [
            "ffmpeg",
            "-y",
            "-hide_banner",
            *inputs,
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-t",
            f"{timeline.duration:.3f}",
            *self._video_encoder_arguments(profile.crf, profile.preset),
            "-c:a",
            "aac",
            "-b:a",
            profile.audio_bitrate,
            "-ar",
            "48000",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output),
        ]

    def _video_encoder_arguments(self, quality: int, preset: str) -> list[str]:
        """Use NVENC when requested, while retaining a portable x264 fallback."""
        if self.settings.video_encoder == "h264_nvenc":
            return [
                "-c:v",
                "h264_nvenc",
                "-preset",
                "p4",
                "-rc",
                "vbr",
                "-cq",
                str(quality),
                "-b:v",
                "0",
            ]
        return ["-c:v", self.settings.video_encoder, "-crf", str(quality), "-preset", preset]

    @staticmethod
    async def _run(command: list[str]) -> None:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode:
            await logger.aerror(
                "production_ffmpeg_failed", stderr=stderr.decode(errors="replace")[-8000:]
            )
            raise MediaProcessingError("Voiceover-driven FFmpeg render failed")

    def _draw_card(self, path: Path, text: str) -> None:
        image = Image.new(
            "RGB", (self.settings.preview_width, self.settings.preview_height), "#0B0F14"
        )
        draw = ImageDraw.Draw(image)
        try:
            font: FreeTypeFont | ImageFont.ImageFont = ImageFont.truetype(
                self.settings.video_font_path, 68
            )
        except OSError:
            font = ImageFont.load_default(size=48)
        wrapped = "\n".join(re.findall(r".{1,22}(?:\s+|$)", text.upper()))
        draw.multiline_text((60, image.height // 3), wrapped, font=font, fill="#F8FAFC", spacing=18)
        draw.rectangle((60, image.height // 3 - 35, 230, image.height // 3 - 20), fill="#55D6BE")
        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, "PNG")


async def probe_json(path: Path) -> dict[str, Any]:
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
    stdout, _ = await process.communicate()
    if process.returncode:
        raise MediaProcessingError("ffprobe failed")
    return json.loads(stdout)
