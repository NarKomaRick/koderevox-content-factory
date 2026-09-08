import asyncio
import textwrap
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

from app.models.enums import ThumbnailPreset
from app.schemas.thumbnails import ThumbnailConcept


def load_font(path: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype(path, size=size)
    except OSError:
        return ImageFont.load_default(size=size)


class CodeCardRenderer:
    async def render(
        self,
        code: str,
        destination: Path,
        *,
        width: int = 900,
        height: int = 1100,
        font_path: str = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    ) -> Path:
        await asyncio.to_thread(self._render_sync, code, destination, width, height, font_path)
        return destination

    @staticmethod
    def _render_sync(code: str, destination: Path, width: int, height: int, font_path: str) -> None:
        image = Image.new("RGB", (width, height), "#121820")
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle((2, 2, width - 3, height - 3), 28, outline="#39424E", width=4)
        for index, color in enumerate(("#FF6B6B", "#FFD166", "#55D6BE")):
            x = 42 + index * 34
            draw.ellipse((x, 32, x + 18, 50), fill=color)
        font = load_font(font_path, 31)
        visible = code[:6000]
        lines: list[str] = []
        for source_line in visible.splitlines()[:40]:
            lines.extend(textwrap.wrap(source_line.expandtabs(2), width=48) or [""])
        y = 92
        colors = {"def": "#70D6FF", "class": "#70D6FF", "return": "#FF70A6", "async": "#70D6FF"}
        for number, line in enumerate(lines[:31], start=1):
            draw.text((34, y), f"{number:>2}", font=font, fill="#667085")
            x = 92
            for token in re_tokenize(line):
                fill = colors.get(token, "#E5E7EB")
                draw.text((x, y), token, font=font, fill=fill)
                x += int(draw.textlength(token, font=font))
            y += 32
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, "PNG", optimize=True)


def re_tokenize(line: str) -> list[str]:
    result: list[str] = []
    token = ""
    for character in line:
        if character.isalnum() or character == "_":
            token += character
        else:
            if token:
                result.append(token)
                token = ""
            result.append(character)
    if token:
        result.append(token)
    return result


class ThumbnailRenderer:
    async def render(
        self,
        concept: ThumbnailConcept,
        destination: Path,
        *,
        subject_path: Path | None,
        width: int,
        height: int,
        font_path: str,
        logo_path: Path | None = None,
    ) -> Path:
        await asyncio.to_thread(
            self._render_sync,
            concept,
            destination,
            subject_path,
            width,
            height,
            font_path,
            logo_path,
        )
        return destination

    @staticmethod
    def _render_sync(
        concept: ThumbnailConcept,
        destination: Path,
        subject_path: Path | None,
        width: int,
        height: int,
        font_path: str,
        logo_path: Path | None,
    ) -> None:
        palette = {
            ThumbnailPreset.TECH_DARK: ("#0B0F14", "#55D6BE", "#F8FAFC"),
            ThumbnailPreset.CLEAN_LIGHT: ("#F4F7FA", "#2864DC", "#111827"),
            ThumbnailPreset.PRODUCT: ("#111827", "#7DD3FC", "#FFFFFF"),
        }
        background, accent, text_color = palette[concept.preset]
        image = Image.new("RGB", (width, height), background)
        draw = ImageDraw.Draw(image)
        draw.rectangle((0, 0, 18, height), fill=accent)
        draw.rectangle((56, 76, 118, 86), fill=accent)
        if subject_path and subject_path.is_file():
            with Image.open(subject_path) as opened:
                subject = ImageOps.exif_transpose(opened).convert("RGB")
                subject = ImageOps.fit(
                    subject, (int(width * 0.48), int(height * 0.76)), Image.Resampling.LANCZOS
                )
                shadow = Image.new("RGBA", subject.size, (0, 0, 0, 0))
                ImageDraw.Draw(shadow).rounded_rectangle(
                    (8, 8, subject.width - 8, subject.height - 8), 28, fill=(0, 0, 0, 180)
                )
                shadow = shadow.filter(ImageFilter.GaussianBlur(14))
                x = width - subject.width - 48
                y = (height - subject.height) // 2
                image.paste(shadow, (x + 10, y + 16), shadow)
                mask = Image.new("L", subject.size, 0)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, *subject.size), 24, fill=255)
                image.paste(subject, (x, y), mask)
        headline = " ".join(concept.headline.upper().split())
        max_text_width = int(width * (0.56 if subject_path else 0.82))
        font_size = 112
        while font_size > 54:
            font = load_font(font_path, font_size)
            lines = textwrap.wrap(headline, width=max(8, int(max_text_width / (font_size * 0.62))))
            boxes = [draw.textbbox((0, 0), line, font=font, stroke_width=1) for line in lines]
            if lines and max(box[2] for box in boxes) <= max_text_width and len(lines) <= 3:
                break
            font_size -= 4
        y = int(height * 0.22)
        for line in lines[:3]:
            draw.text((60, y), line, font=font, fill=text_color, stroke_width=1)
            y += int(font_size * 1.06)
        draw.text(
            (62, height - 76),
            "KODEREVOX  /  ENGINEERING",
            font=load_font(font_path, 24),
            fill=accent,
        )
        if logo_path and logo_path.is_file():
            with Image.open(logo_path) as opened:
                logo = opened.convert("RGBA")
                logo.thumbnail((180, 64), Image.Resampling.LANCZOS)
                image.paste(logo, (width - logo.width - 52, 30), logo)
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, "JPEG", quality=92, optimize=True)
