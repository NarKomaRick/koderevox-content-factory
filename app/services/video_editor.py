import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import structlog

from app.models.enums import FramingMode
from app.schemas.video import EditPlan
from app.schemas.visual import VisualInsertion
from app.services.audio import AudioProcessor
from app.services.framing import FramingProvider, StaticFramingProvider
from app.services.media import MediaProcessingError
from app.services.pause import TimeRange

logger = structlog.get_logger()


@dataclass(frozen=True)
class RenderResult:
    output_path: Path
    duration: float
    width: int
    height: int
    size_bytes: int
    video_codec: str
    audio_codec: str


@dataclass(frozen=True)
class VisualRenderAsset:
    insertion: VisualInsertion
    path: Path
    is_video: bool = False


class VideoEditor(Protocol):
    async def render(
        self,
        *,
        source: Path,
        destination: Path,
        clips: list[TimeRange],
        plan: EditPlan,
        subtitle_file: Path,
        settings: dict[str, Any],
        visuals: list[VisualRenderAsset] | None = None,
    ) -> RenderResult: ...


class FFmpegVideoEditor:
    def __init__(
        self,
        framing_provider: FramingProvider | None = None,
        font_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ) -> None:
        self.framing = framing_provider or StaticFramingProvider()
        self.font_path = font_path

    async def render(
        self,
        *,
        source: Path,
        destination: Path,
        clips: list[TimeRange],
        plan: EditPlan,
        subtitle_file: Path,
        settings: dict[str, Any],
        visuals: list[VisualRenderAsset] | None = None,
    ) -> RenderResult:
        destination.parent.mkdir(parents=True, exist_ok=True)
        command = self.build_command(
            source=source,
            destination=destination,
            clips=clips,
            plan=plan,
            subtitle_file=subtitle_file,
            settings=settings,
            visuals=visuals,
        )
        await self._run(command, "video render")
        result = await self.validate_output(
            destination,
            expected_width=int(settings["width"]),
            expected_height=int(settings["height"]),
        )
        await logger.ainfo(
            "video_render_completed",
            output=str(destination),
            duration=result.duration,
            size_bytes=result.size_bytes,
        )
        return result

    def build_command(
        self,
        *,
        source: Path,
        destination: Path,
        clips: list[TimeRange],
        plan: EditPlan,
        subtitle_file: Path,
        settings: dict[str, Any],
        visuals: list[VisualRenderAsset] | None = None,
    ) -> list[str]:
        if not clips:
            raise ValueError("At least one render clip is required")
        filters: list[str] = []
        concat_inputs: list[str] = []
        for index, clip in enumerate(clips):
            filters.append(
                f"[0:v]trim=start={clip.start:.3f}:end={clip.end:.3f},setpts=PTS-STARTPTS[v{index}]"
            )
            filters.append(
                f"[0:a]atrim=start={clip.start:.3f}:end={clip.end:.3f},"
                f"asetpts=PTS-STARTPTS[a{index}]"
            )
            concat_inputs.append(f"[v{index}][a{index}]")
        filters.append("".join(concat_inputs) + f"concat=n={len(clips)}:v=1:a=1[vcat][acat]")
        width = int(settings["width"])
        height = int(settings["height"])
        filters.append(
            self.framing.filter_graph(
                "vcat",
                "framed",
                FramingMode(plan.framing),
                width=width,
                height=height,
                manual=plan.manual_framing,
            )
        )
        command_inputs = ["-i", str(source)]
        video_input = "framed"
        for input_index, visual in enumerate(visuals or [], start=1):
            duration = visual.insertion.end - visual.insertion.start
            if visual.is_video:
                command_inputs.extend(["-stream_loop", "-1", "-i", str(visual.path)])
            else:
                command_inputs.extend(
                    ["-loop", "1", "-t", f"{duration:.3f}", "-i", str(visual.path)]
                )
            prepared = f"vis{input_index}"
            width = int(settings["width"])
            height = int(settings["height"])
            layout = visual.insertion.layout.value
            if layout in {"fullscreen", "background"}:
                prepared_w, prepared_h = width, height
                visual_filter = (
                    f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x10141b"
                )
                if layout == "background":
                    visual_filter += ",colorchannelmixer=aa=0.55"
                x, y = "0", "0"
            elif layout == "side_by_side":
                prepared_w, prepared_h = width, height // 2
                visual_filter = (
                    f"scale={width}:{height // 2}:force_original_aspect_ratio=decrease,"
                    f"pad={width}:{height // 2}:(ow-iw)/2:(oh-ih)/2:color=0x10141b"
                )
                x, y = "0", "0"
            else:
                if layout == "code_card":
                    target_w, target_h = int(width * 0.78), int(height * 0.62)
                elif layout == "device_frame":
                    target_w, target_h = int(width * 0.58), int(height * 0.62)
                else:
                    target_w, target_h = int(width * 0.46), int(height * 0.34)
                prepared_w, prepared_h = target_w, target_h
                visual_filter = (
                    f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
                    f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=0x151a22,"
                    "drawbox=x=0:y=0:w=iw:h=ih:color=white@0.25:t=4"
                )
                x = "(W-w)/2" if layout in {"device_frame", "code_card"} else "W-w-60"
                y = str(int(settings.get("safe_margin_top", 160)))
            transition_filter = ""
            transition = visual.insertion.transition.value
            if transition == "fade":
                fade_out = max(0.0, duration - 0.25)
                transition_filter = (
                    f",fade=t=in:st={visual.insertion.start:.3f}:d=0.25:alpha=1,"
                    f"fade=t=out:st={visual.insertion.start + fade_out:.3f}:d=0.25:alpha=1"
                )
            elif transition == "scale_in":
                transition_filter = (
                    ",zoompan=z='max(1.0,1.08-on*0.01)':d=1:"
                    f"s={prepared_w}x{prepared_h}:fps={int(settings['fps'])}"
                )
            if transition == "slide":
                finish = visual.insertion.start + 0.3
                x = f"'{x}+max(0,{finish:.3f}-t)*W/0.3'"
            filters.append(
                f"[{input_index}:v]trim=duration={duration:.3f},setpts=PTS-STARTPTS+"
                f"{visual.insertion.start:.3f}/TB,{visual_filter},format=rgba"
                f"{transition_filter}"
                f"[{prepared}]"
            )
            composed = f"composed{input_index}"
            filters.append(
                f"[{video_input}][{prepared}]overlay=x={x}:y={y}:eof_action=pass:shortest=0:"
                f"enable='between(t,{visual.insertion.start:.3f},{visual.insertion.end:.3f})'"
                f"[{composed}]"
            )
            video_input = composed
        subtitle_path = self._filter_path(subtitle_file)
        filters.append(f"[{video_input}]ass=filename='{subtitle_path}'[subtitled]")
        video_input = "subtitled"
        if bool(settings.get("hook_overlay", True)) and plan.hook_text:
            hook = self._drawtext_value(plan.hook_text)
            font = self._filter_path(Path(self.font_path))
            filters.append(
                f"[{video_input}]drawtext=fontfile='{font}':text='{hook}':"
                "fontcolor=white:fontsize=54:borderw=3:bordercolor=black@0.65:"
                "x=(w-text_w)/2:y=h*0.08:enable='between(t,0,3)'[hooked]"
            )
            video_input = "hooked"
        fps = int(settings["fps"])
        filters.append(f"[{video_input}]fps={fps},format=yuv420p[vout]")
        audio = AudioProcessor(
            normalization_enabled=bool(settings.get("audio_normalization", True)),
            noise_reduction_enabled=bool(settings.get("noise_reduction", False)),
        )
        filters.append(f"[acat]{audio.ffmpeg_filter()}[aout]")
        return [
            "ffmpeg",
            "-y",
            "-hide_banner",
            *command_inputs,
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[vout]",
            "-map",
            "[aout]",
            "-c:v",
            "libx264",
            "-crf",
            str(settings["crf"]),
            "-preset",
            str(settings["preset"]),
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-ar",
            "48000",
            "-movflags",
            "+faststart",
            "-pix_fmt",
            "yuv420p",
            str(destination),
        ]

    async def validate_output(
        self, path: Path, *, expected_width: int, expected_height: int
    ) -> RenderResult:
        process = await asyncio.create_subprocess_exec(
            "ffprobe",
            "-v",
            "error",
            "-show_format",
            "-show_streams",
            "-of",
            "json",
            str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            raise MediaProcessingError("Rendered file failed ffprobe validation")
        probe = json.loads(stdout)
        video = next(
            (stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"),
            None,
        )
        audio = next(
            (stream for stream in probe.get("streams", []) if stream.get("codec_type") == "audio"),
            None,
        )
        if not video or not audio:
            raise MediaProcessingError("Rendered file must contain video and audio")
        if video.get("codec_name") != "h264" or audio.get("codec_name") != "aac":
            raise MediaProcessingError("Rendered file codecs are not H.264/AAC")
        if video.get("width") != expected_width or video.get("height") != expected_height:
            raise MediaProcessingError("Rendered file has unexpected dimensions")
        duration = float(probe.get("format", {}).get("duration") or 0)
        if duration <= 0:
            raise MediaProcessingError("Rendered file has invalid duration")
        stat = await asyncio.to_thread(path.stat)
        return RenderResult(
            output_path=path,
            duration=duration,
            width=int(video["width"]),
            height=int(video["height"]),
            size_bytes=stat.st_size,
            video_codec=str(video["codec_name"]),
            audio_codec=str(audio["codec_name"]),
        )

    async def extract_preview_frames(
        self, source: Path, destination: Path, duration: float
    ) -> list[Path]:
        await asyncio.to_thread(destination.mkdir, parents=True, exist_ok=True)
        frames: list[Path] = []
        for index, ratio in enumerate((0.05, 0.25, 0.5, 0.75)):
            frame = destination / f"frame-{index}.jpg"
            command = [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-ss",
                f"{max(0, duration * ratio):.3f}",
                "-i",
                str(source),
                "-frames:v",
                "1",
                "-q:v",
                "3",
                str(frame),
            ]
            await self._run(command, "preview frame extraction")
            if frame.stat().st_size <= 100:
                raise MediaProcessingError("Extracted preview frame is empty")
            frames.append(frame)
        return frames

    async def extract_debug_frames(
        self, source: Path, destination: Path, times: list[float]
    ) -> list[Path]:
        await asyncio.to_thread(destination.mkdir, parents=True, exist_ok=True)
        frames: list[Path] = []
        for index, timestamp in enumerate(times):
            frame = destination / f"debug-{index}-{timestamp:.2f}.jpg"
            await self._run(
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-ss",
                    f"{max(0, timestamp):.3f}",
                    "-i",
                    str(source),
                    "-frames:v",
                    "1",
                    "-q:v",
                    "2",
                    str(frame),
                ],
                "debug frame extraction",
            )
            frames.append(frame)
        return frames

    async def compress_preview(
        self, source: Path, destination: Path, *, width: int = 720, height: int = 1280
    ) -> Path:
        command = [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-i",
            str(source),
            "-vf",
            f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
            f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:black",
            "-c:v",
            "libx264",
            "-crf",
            "29",
            "-preset",
            "veryfast",
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(destination),
        ]
        await self._run(command, "preview compression")
        return destination

    @staticmethod
    async def _run(command: list[str], operation: str) -> None:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await process.communicate()
        if process.returncode != 0:
            await logger.aerror(
                "ffmpeg_failed",
                operation=operation,
                stderr=stderr.decode(errors="replace")[-8000:],
            )
            raise MediaProcessingError(f"FFmpeg {operation} failed")

    @staticmethod
    def _filter_path(path: Path) -> str:
        return str(path.resolve()).replace("\\", "/").replace(":", r"\:").replace("'", r"\'")

    @staticmethod
    def _drawtext_value(text: str) -> str:
        return (
            text.replace("\\", r"\\")
            .replace("'", r"\'")
            .replace(":", r"\:")
            .replace("%", r"\%")
            .replace("\n", " ")
        )
