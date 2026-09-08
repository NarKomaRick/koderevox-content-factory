import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.models.enums import SubtitlePreset
from app.schemas.processing import TranscriptSegment, TranscriptWord
from app.services.pause import TimeRange
from app.services.subtitle_presets import SubtitleStyle, get_subtitle_style


@dataclass(frozen=True)
class TimedWord:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class SubtitleCue:
    start: float
    end: float
    text: str
    words: tuple[TimedWord, ...] = ()


class SubtitleService:
    def create_cues(
        self,
        segments: list[dict[str, Any]],
        clips: list[TimeRange],
        *,
        preset: SubtitlePreset,
        vocabulary: list[str] | None = None,
        overrides: dict[str, str] | None = None,
    ) -> list[SubtitleCue]:
        style = get_subtitle_style(preset)
        words = self._timeline_words(segments, clips)
        cues = self._chunk(words, style)
        replacements = self._replacement_map(vocabulary or [], overrides or {})
        return [
            SubtitleCue(
                cue.start,
                cue.end,
                self._replace(cue.text, replacements),
                cue.words,
            )
            for cue in cues
        ]

    def write_ass(
        self,
        destination: Path,
        cues: list[SubtitleCue],
        *,
        preset: SubtitlePreset,
        width: int,
        height: int,
        emphasis: list[str] | None = None,
    ) -> Path:
        style = get_subtitle_style(preset)
        destination.parent.mkdir(parents=True, exist_ok=True)
        header = self._ass_header(style, width, height)
        emphasis_normalized = {item.casefold() for item in (emphasis or [])}
        events = []
        for cue in cues:
            if preset == SubtitlePreset.DYNAMIC:
                text = self._karaoke_text(cue)
            else:
                text = self.escape_ass(cue.text)
                for phrase in emphasis_normalized:
                    if phrase and phrase in cue.text.casefold():
                        pattern = re.compile(re.escape(phrase), re.IGNORECASE)
                        text = pattern.sub(
                            rf"{{\c{style.highlight_color}\b1}}\g<0>{{\r{style.name}}}",
                            text,
                        )
            events.append(
                f"Dialogue: 0,{self.ass_time(cue.start)},{self.ass_time(cue.end)},"
                f"{style.name},,0,0,0,,{text}"
            )
        destination.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
        return destination

    def write_srt(self, destination: Path, cues: list[SubtitleCue]) -> Path:
        blocks = [
            f"{index}\n{self.srt_time(cue.start)} --> {self.srt_time(cue.end)}\n{cue.text}\n"
            for index, cue in enumerate(cues, start=1)
        ]
        destination.write_text("\n".join(blocks), encoding="utf-8")
        return destination

    def _timeline_words(
        self, raw_segments: list[dict[str, Any]], clips: list[TimeRange]
    ) -> list[TimedWord]:
        segments = [TranscriptSegment.model_validate(item) for item in raw_segments]
        output: list[TimedWord] = []
        output_offset = 0.0
        for clip in clips:
            for segment in segments:
                if segment.end <= clip.start or segment.start >= clip.end:
                    continue
                source_words = segment.words or self._estimate_words(segment)
                for word in source_words:
                    if word.end <= clip.start or word.start >= clip.end:
                        continue
                    start = output_offset + max(word.start, clip.start) - clip.start
                    end = output_offset + min(word.end, clip.end) - clip.start
                    if end > start:
                        output.append(TimedWord(word.word, start, end))
            output_offset += clip.duration
        return output

    @staticmethod
    def _estimate_words(segment: TranscriptSegment) -> list[TranscriptWord]:
        tokens = segment.text.split()
        if not tokens:
            return []
        step = (segment.end - segment.start) / len(tokens)
        return [
            TranscriptWord(
                word=token,
                start=segment.start + index * step,
                end=segment.start + (index + 1) * step,
            )
            for index, token in enumerate(tokens)
        ]

    @staticmethod
    def _chunk(words: list[TimedWord], style: SubtitleStyle) -> list[SubtitleCue]:
        cues: list[SubtitleCue] = []
        current: list[TimedWord] = []
        for word in words:
            candidate = " ".join([*(item.text for item in current), word.text])
            boundary = bool(current and current[-1].text.rstrip().endswith((".", "!", "?", ":")))
            if current and (
                len(current) >= style.max_words or len(candidate) > style.max_chars or boundary
            ):
                cues.append(
                    SubtitleCue(
                        current[0].start,
                        current[-1].end,
                        " ".join(w.text for w in current),
                        tuple(current),
                    )
                )
                current = []
            current.append(word)
        if current:
            cues.append(
                SubtitleCue(
                    current[0].start,
                    current[-1].end,
                    " ".join(w.text for w in current),
                    tuple(current),
                )
            )
        return cues

    def _karaoke_text(self, cue: SubtitleCue) -> str:
        display_words = cue.text.split()
        if not display_words:
            return ""
        if cue.words and len(cue.words) == len(display_words):
            durations = [max(1, round((word.end - word.start) * 100)) for word in cue.words]
        else:
            duration = max(1, round((cue.end - cue.start) * 100 / len(display_words)))
            durations = [duration] * len(display_words)
        return " ".join(
            f"{{\\kf{duration}}}{self.escape_ass(word)}"
            for word, duration in zip(display_words, durations, strict=True)
        )

    @staticmethod
    def _replacement_map(vocabulary: list[str], overrides: dict[str, str]) -> dict[str, str]:
        replacements = {term.casefold(): term for term in vocabulary if term.strip()}
        replacements.update({old.casefold(): new for old, new in overrides.items()})
        return replacements

    @staticmethod
    def _replace(text: str, replacements: dict[str, str]) -> str:
        result = text
        for old, new in sorted(replacements.items(), key=lambda item: len(item[0]), reverse=True):
            result = re.sub(rf"(?<!\w){re.escape(old)}(?!\w)", new, result, flags=re.IGNORECASE)
        return result

    @staticmethod
    def escape_ass(text: str) -> str:
        return (
            text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")
        )

    @staticmethod
    def ass_time(seconds: float) -> str:
        centiseconds = max(0, round(seconds * 100))
        hours, remainder = divmod(centiseconds, 360_000)
        minutes, remainder = divmod(remainder, 6_000)
        whole_seconds, fraction = divmod(remainder, 100)
        return f"{hours}:{minutes:02d}:{whole_seconds:02d}.{fraction:02d}"

    @staticmethod
    def srt_time(seconds: float) -> str:
        milliseconds = max(0, round(seconds * 1000))
        hours, remainder = divmod(milliseconds, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        whole_seconds, fraction = divmod(remainder, 1000)
        return f"{hours:02d}:{minutes:02d}:{whole_seconds:02d},{fraction:03d}"

    @staticmethod
    def _ass_header(style: SubtitleStyle, width: int, height: int) -> str:
        style_format = ", ".join(
            [
                "Name",
                "Fontname",
                "Fontsize",
                "PrimaryColour",
                "SecondaryColour",
                "OutlineColour",
                "BackColour",
                "Bold",
                "Italic",
                "Underline",
                "StrikeOut",
                "ScaleX",
                "ScaleY",
                "Spacing",
                "Angle",
                "BorderStyle",
                "Outline",
                "Shadow",
                "Alignment",
                "MarginL",
                "MarginR",
                "MarginV",
                "Encoding",
            ]
        )
        style_line = ",".join(
            [
                style.name,
                style.font_name,
                str(style.font_size),
                style.primary_color,
                style.highlight_color,
                style.outline_color,
                "&H50000000",
                "0,0,0,0,100,100,0,0,1",
                str(style.outline),
                str(style.shadow),
                "2,80,80",
                str(style.margin_v),
                "1",
            ]
        )
        return (
            "[Script Info]\n"
            "ScriptType: v4.00+\n"
            f"PlayResX: {width}\n"
            f"PlayResY: {height}\n"
            "WrapStyle: 2\n"
            "ScaledBorderAndShadow: yes\n\n"
            "[V4+ Styles]\n"
            f"Format: {style_format}\n"
            f"Style: {style_line}\n\n"
            "[Events]\n"
            "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
        )
