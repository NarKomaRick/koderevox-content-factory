"""Deterministic text placement; the Director chooses intent, not pixel geometry."""

from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from app.director.schemas import Anchor, OutputProfile


@dataclass(frozen=True)
class TextBox:
    x: int
    y: int
    width: int
    height: int
    font_size: int
    text: str
    anchor: str

    @property
    def right(self) -> int:
        return self.x + self.width

    @property
    def bottom(self) -> int:
        return self.y + self.height


class LayoutEngine:
    def __init__(self, *, font_path: str | None = None) -> None:
        self.font_path = font_path

    def measure(self, text: str, *, font_size: int, max_width: int) -> tuple[str, int, int]:
        font = self._font(font_size)
        words = text.split()
        lines: list[str] = []
        current = ""
        for word in words or [text]:
            candidate = f"{current} {word}".strip()
            if current and self._width(font, candidate) > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        wrapped = "\n".join(lines) or " "
        drawer = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        bbox = drawer.multiline_textbbox((0, 0), wrapped, font=font, spacing=max(4, font_size // 5))
        return wrapped, max(1, int(bbox[2] - bbox[0])), max(1, int(bbox[3] - bbox[1]))

    def place(
        self,
        text: str,
        profile: OutputProfile,
        *,
        anchor: Anchor = "auto",
        font_size: int | None = None,
        occupied: list[TextBox] | None = None,
        minimum_font_size: int = 28,
    ) -> TextBox:
        occupied = occupied or []
        size = font_size or profile.recommended_text_sizes.get("body", 52)
        safe = profile.safe_zones
        max_width = profile.width - safe.left - safe.right
        for candidate_size in range(size, minimum_font_size - 1, -2):
            wrapped, width, height = self.measure(
                text, font_size=candidate_size, max_width=max_width
            )
            width = min(width, max_width)
            for candidate_anchor in self._anchors(anchor):
                x, y = self._origin(candidate_anchor, width, height, profile)
                box = TextBox(x, y, width, height, candidate_size, wrapped, candidate_anchor)
                if self._inside_safe(box, profile) and not any(
                    self.overlaps(box, item) for item in occupied
                ):
                    return box
        wrapped, width, height = self.measure(
            text, font_size=minimum_font_size, max_width=max_width
        )
        x, y = self._origin("top_center", min(width, max_width), height, profile)
        return TextBox(
            x, y, min(width, max_width), height, minimum_font_size, wrapped, "top_center"
        )

    @staticmethod
    def overlaps(left: TextBox, right: TextBox) -> bool:
        return (
            left.x < right.right
            and right.x < left.right
            and left.y < right.bottom
            and right.y < left.bottom
        )

    def _font(self, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
        if self.font_path:
            try:
                return ImageFont.truetype(self.font_path, size)
            except OSError:
                pass
        return ImageFont.load_default(size=size)

    @staticmethod
    def _width(font: ImageFont.FreeTypeFont | ImageFont.ImageFont, text: str) -> int:
        return int(font.getbbox(text)[2])

    @staticmethod
    def _anchors(anchor: Anchor) -> list[str]:
        return (
            [anchor]
            if anchor != "auto"
            else [
                "top_center",
                "center",
                "bottom_center",
                "top_left",
                "top_right",
                "bottom_left",
                "bottom_right",
            ]
        )

    @staticmethod
    def _origin(anchor: str, width: int, height: int, profile: OutputProfile) -> tuple[int, int]:
        safe = profile.safe_zones
        left, right = safe.left, profile.width - safe.right
        top, bottom = safe.top, profile.height - safe.bottom
        x = {
            "top_left": left,
            "center": (profile.width - width) // 2,
            "bottom_left": left,
            "top_center": (profile.width - width) // 2,
            "bottom_center": (profile.width - width) // 2,
            "top_right": right - width,
            "bottom_right": right - width,
        }.get(anchor, (profile.width - width) // 2)
        y = {
            "top_left": top,
            "top_center": top,
            "top_right": top,
            "center": (profile.height - height) // 2,
            "bottom_left": bottom - height,
            "bottom_center": bottom - height,
            "bottom_right": bottom - height,
        }.get(anchor, top)
        return max(0, x), max(0, y)

    @staticmethod
    def _inside_safe(box: TextBox, profile: OutputProfile) -> bool:
        safe = profile.safe_zones
        return (
            box.x >= safe.left
            and box.right <= profile.width - safe.right
            and box.y >= safe.top
            and box.bottom <= profile.height - safe.bottom
        )
