from typing import Protocol

from app.models.enums import FramingMode
from app.schemas.video import ManualFraming


class FramingProvider(Protocol):
    def filter_graph(
        self,
        input_label: str,
        output_label: str,
        mode: FramingMode,
        *,
        width: int,
        height: int,
        manual: ManualFraming | None = None,
    ) -> str: ...


class StaticFramingProvider:
    def filter_graph(
        self,
        input_label: str,
        output_label: str,
        mode: FramingMode,
        *,
        width: int,
        height: int,
        manual: ManualFraming | None = None,
    ) -> str:
        if mode in {FramingMode.FIT_BLUR, FramingMode.SCREEN_FIT}:
            blur = 24 if mode == FramingMode.FIT_BLUR else 12
            return (
                f"[{input_label}]split=2[frame_bg][frame_fg];"
                f"[frame_bg]scale={width}:{height}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height},boxblur={blur}:{blur}[blurred];"
                f"[frame_fg]scale={width}:{height}:force_original_aspect_ratio=decrease[fit];"
                f"[blurred][fit]overlay=(W-w)/2:(H-h)/2[{output_label}]"
            )
        if mode == FramingMode.MANUAL and manual is not None:
            scaled_width = round(width * manual.zoom)
            scaled_height = round(height * manual.zoom)
            x_expr = f"(iw-ow)*{manual.x}"
            y_expr = f"(ih-oh)*{manual.y}"
            return (
                f"[{input_label}]scale={scaled_width}:{scaled_height}:"
                "force_original_aspect_ratio=increase,"
                f"crop={width}:{height}:{x_expr}:{y_expr}[{output_label}]"
            )
        return (
            f"[{input_label}]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height}[{output_label}]"
        )
