from dataclasses import dataclass

from app.models.enums import SubtitlePreset


@dataclass(frozen=True)
class SubtitleStyle:
    name: str
    font_name: str
    font_size: int
    primary_color: str
    highlight_color: str
    outline_color: str
    outline: int
    shadow: int
    margin_v: int
    max_words: int
    max_chars: int


PRESETS = {
    SubtitlePreset.CLEAN: SubtitleStyle(
        "Clean", "DejaVu Sans", 54, "&H00FFFFFF", "&H0000D7FF", "&H90000000", 2, 1, 210, 6, 38
    ),
    SubtitlePreset.DYNAMIC: SubtitleStyle(
        "Dynamic", "DejaVu Sans", 60, "&H00FFFFFF", "&H0000D7FF", "&HA0000000", 3, 1, 220, 3, 26
    ),
    SubtitlePreset.TECH: SubtitleStyle(
        "Tech", "DejaVu Sans", 52, "&H00FFFFFF", "&H00D9C46C", "&HA0000000", 2, 0, 200, 5, 34
    ),
}


def get_subtitle_style(preset: SubtitlePreset) -> SubtitleStyle:
    return PRESETS[preset]
