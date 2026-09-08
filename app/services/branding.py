from dataclasses import dataclass

from app.models.enums import SubtitlePreset


@dataclass(frozen=True)
class BrandPreset:
    name: str
    font_path: str
    subtitle_preset: SubtitlePreset
    horizontal_margin: int = 80
    logo_path: str | None = None
    watermark_enabled: bool = False
    outro_path: str | None = None


def koderevox_brand(font_path: str) -> BrandPreset:
    """Minimal defaults: no permanent logo, watermark or forced outro."""
    return BrandPreset(
        name="Koderevox",
        font_path=font_path,
        subtitle_preset=SubtitlePreset.TECH,
    )
