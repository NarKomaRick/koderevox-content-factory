from dataclasses import dataclass
from typing import Any

from app.models.enums import SubtitlePreset, ThumbnailPreset


@dataclass(frozen=True)
class BrandPreset:
    name: str
    font_path: str
    subtitle_preset: SubtitlePreset
    horizontal_margin: int = 80
    logo_path: str | None = None
    watermark_enabled: bool = False
    outro_path: str | None = None
    primary_color: str = "#10141B"
    accent_color: str = "#55D6BE"
    text_color: str = "#F4F7FA"
    thumbnail_preset: ThumbnailPreset = ThumbnailPreset.TECH_DARK
    secondary_font_path: str | None = None
    safe_margin_top: int = 140
    safe_margin_bottom: int = 360

    def serialize(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "font_path": self.font_path,
            "secondary_font_path": self.secondary_font_path,
            "subtitle_preset": self.subtitle_preset.value,
            "thumbnail_preset": self.thumbnail_preset.value,
            "horizontal_margin": self.horizontal_margin,
            "safe_margin_top": self.safe_margin_top,
            "safe_margin_bottom": self.safe_margin_bottom,
            "logo_path": self.logo_path,
            "watermark_enabled": self.watermark_enabled,
            "outro_path": self.outro_path,
            "primary_color": self.primary_color,
            "accent_color": self.accent_color,
            "text_color": self.text_color,
        }


def koderevox_brand(font_path: str) -> BrandPreset:
    """Minimal defaults: no permanent logo, watermark or forced outro."""
    return BrandPreset(
        name="Koderevox",
        font_path=font_path,
        subtitle_preset=SubtitlePreset.TECH,
    )
