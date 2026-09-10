"""Portable Pillow graphics renderer behind the stable Director graphics DSL."""

import asyncio
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw

from app.services.graphics import load_font


class GraphicsRenderer:
    async def render(
        self,
        kind: str,
        content: dict[str, Any],
        destination: Path,
        *,
        width: int,
        height: int,
        font_path: str,
        style: str = "technical",
    ) -> Path:
        await asyncio.to_thread(
            self._render_sync, kind, content, destination, width, height, font_path, style
        )
        return destination

    @staticmethod
    def _render_sync(
        kind: str,
        content: dict[str, Any],
        destination: Path,
        width: int,
        height: int,
        font_path: str,
        style: str,
    ) -> None:
        image = Image.new("RGBA", (width, height), (11, 15, 20, 0))
        draw = ImageDraw.Draw(image)
        accent = "#55D6BE" if style != "warning" else "#FFB454"
        card = (int(width * 0.08), int(height * 0.30), int(width * 0.92), int(height * 0.70))
        draw.rounded_rectangle(card, radius=28, fill=(16, 20, 27, 245), outline=accent, width=4)
        title_font = load_font(font_path, max(32, width // 18))
        body_font = load_font(font_path, max(24, width // 28))
        value = str(content.get("value", content.get("title", content.get("text", ""))))
        label = str(content.get("label", content.get("description", "")))
        if kind in {"stat_card", "quote", "title_card", "warning_card"}:
            draw.text((card[0] + 48, card[1] + 55), value[:80], font=title_font, fill="#F8FAFC")
            if label:
                draw.multiline_text(
                    (card[0] + 48, card[1] + 180),
                    label[:240],
                    font=body_font,
                    fill="#CBD5E1",
                    spacing=10,
                )
        elif kind in {"arrow", "circle_highlight", "rectangle_highlight"}:
            draw.line(
                (card[0] + 80, card[1] + 180, card[2] - 100, card[1] + 180), fill=accent, width=12
            )
            draw.polygon(
                (
                    (card[2] - 100, card[1] + 180),
                    (card[2] - 150, card[1] + 140),
                    (card[2] - 150, card[1] + 220),
                ),
                fill=accent,
            )
        else:
            draw.text((card[0] + 48, card[1] + 55), value[:120], font=title_font, fill="#F8FAFC")
            if label:
                draw.multiline_text(
                    (card[0] + 48, card[1] + 170),
                    label[:320],
                    font=body_font,
                    fill="#CBD5E1",
                    spacing=10,
                )
        destination.parent.mkdir(parents=True, exist_ok=True)
        image.save(destination, "PNG")
