"""Deterministic audio analysis using voiceover timestamps and optional WAV RMS."""

import asyncio
import math
import wave
from pathlib import Path
from typing import Any

from app.director.schemas import AudioIntelligence, AudioWindow, AudioWordSignal, PauseSignal


class AudioIntelligenceAnalyzer:
    """Extracts useful pacing signals without pretending to be an emotion model."""

    async def analyze(self, voiceover: Any, *, audio_path: Path | None = None) -> AudioIntelligence:
        duration = float(getattr(voiceover, "duration", 0) or voiceover.get("duration", 0))
        segments = self._items(voiceover, "segments")
        words = self._items(voiceover, "words")
        result = self.from_metadata(duration, segments, words)
        if audio_path is not None and await asyncio.to_thread(audio_path.is_file):
            loudness = await asyncio.to_thread(self._wav_energy, audio_path, duration)
            if loudness:
                result = result.model_copy(
                    update={
                        "windows": [
                            window.model_copy(
                                update={
                                    "energy": round(loudness[index], 4),
                                    "relative_loudness": round(loudness[index], 4),
                                }
                            )
                            for index, window in enumerate(result.windows)
                        ],
                        "source": "mixed",
                    }
                )
        return result

    def from_metadata(
        self, duration: float, segments: list[dict[str, Any]], words: list[dict[str, Any]]
    ) -> AudioIntelligence:
        duration = max(0.0, duration)
        windows = self._windows(duration, segments, words)
        pauses = self._pauses(duration, segments, words)
        emphasis = self._emphasis(words)
        boundaries = [
            {
                "start": float(item.get("start", 0)),
                "end": float(item.get("end", 0)),
                "text": str(item.get("text") or item.get("voice_text") or "")[:500],
            }
            for item in segments[:200]
            if float(item.get("end", 0)) > float(item.get("start", 0))
        ]
        return AudioIntelligence(
            duration=duration,
            windows=windows,
            pauses=pauses,
            emphasis=emphasis,
            sentence_boundaries=boundaries,
            phrase_boundaries=boundaries,
        )

    @staticmethod
    def _items(source: Any, name: str) -> list[dict[str, Any]]:
        value = getattr(source, name, None) if not isinstance(source, dict) else source.get(name)
        return [item for item in (value or []) if isinstance(item, dict)]

    def _windows(
        self, duration: float, segments: list[dict[str, Any]], words: list[dict[str, Any]]
    ) -> list[AudioWindow]:
        source = segments or self._word_windows(duration, words)
        result: list[AudioWindow] = []
        for item in source[:100]:
            start = max(0.0, float(item.get("start", 0)))
            end = min(duration or float(item.get("end", 0)), float(item.get("end", 0)))
            if end <= start:
                continue
            count = sum(1 for word in words if start <= float(word.get("start", 0)) < end)
            text = str(item.get("text") or item.get("voice_text") or "")
            count = max(count, len(text.split()))
            wps = count / max(end - start, 0.1)
            result.append(
                AudioWindow(
                    start=start,
                    end=end,
                    words_per_second=round(wps, 3),
                    speech_rate=self._rate(wps),
                    energy=0.5,
                    relative_loudness=0.5,
                )
            )
        return result

    @staticmethod
    def _word_windows(duration: float, words: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not words:
            return [{"start": 0, "end": duration, "text": ""}] if duration else []
        buckets: list[dict[str, Any]] = []
        bucket: list[dict[str, Any]] = []
        start = float(words[0].get("start", 0))
        for word in words:
            bucket.append(word)
            end = float(word.get("end", word.get("start", start)))
            if len(bucket) >= 12 or end - start >= 4:
                buckets.append(
                    {
                        "start": start,
                        "end": end,
                        "text": " ".join(str(x.get("word", x.get("text", ""))) for x in bucket),
                    }
                )
                bucket = []
                start = end
        if bucket:
            end = float(bucket[-1].get("end", start))
            buckets.append(
                {
                    "start": start,
                    "end": end,
                    "text": " ".join(str(x.get("word", x.get("text", ""))) for x in bucket),
                }
            )
        return buckets

    @staticmethod
    def _rate(wps: float) -> str:
        if wps < 2.2:
            return "slow"
        if wps > 3.8:
            return "fast"
        return "medium"

    @staticmethod
    def _pauses(
        duration: float, segments: list[dict[str, Any]], words: list[dict[str, Any]]
    ) -> list[PauseSignal]:
        source = segments or words
        if not source:
            return []
        pauses: list[PauseSignal] = []
        cursor = 0.0
        for item in source:
            start = max(cursor, float(item.get("start", cursor)))
            gap = start - cursor
            if gap >= 0.12:
                pauses.append(
                    PauseSignal(
                        start=cursor,
                        end=start,
                        duration=gap,
                        kind=(
                            "micro"
                            if gap < 0.25
                            else "short"
                            if gap < 0.6
                            else "medium"
                            if gap < 1.2
                            else "long"
                        ),
                    )
                )
            cursor = max(cursor, float(item.get("end", start)))
        if duration - cursor >= 0.12:
            gap = duration - cursor
            pauses.append(
                PauseSignal(
                    start=cursor,
                    end=duration,
                    duration=gap,
                    kind="micro"
                    if gap < 0.25
                    else "short"
                    if gap < 0.6
                    else "medium"
                    if gap < 1.2
                    else "long",
                )
            )
        return pauses[:200]

    @staticmethod
    def _emphasis(words: list[dict[str, Any]]) -> list[AudioWordSignal]:
        durations = [
            max(0.05, float(item.get("end", 0)) - float(item.get("start", 0)))
            for item in words
            if float(item.get("end", 0)) > float(item.get("start", 0))
        ]
        median = sorted(durations)[len(durations) // 2] if durations else 0.3
        result: list[AudioWordSignal] = []
        for item in words[:300]:
            start, end = float(item.get("start", 0)), float(item.get("end", 0))
            text = str(item.get("word") or item.get("text") or "").strip()
            if not text or end <= start:
                continue
            word_duration = max(0.05, end - start)
            duration_signal = min(1.0, word_duration / max(median * 1.8, 0.1))
            text_signal = 0.2 if any(char in text for char in "!?") else 0.0
            score = min(1.0, 0.65 * duration_signal + text_signal)
            if score >= 0.45:
                result.append(
                    AudioWordSignal(
                        start=start,
                        end=end,
                        text=text[:200],
                        emphasis_score=round(score, 3),
                        energy=round(score, 3),
                    )
                )
        return result

    @staticmethod
    def _wav_energy(path: Path, duration: float) -> list[float]:
        try:
            with wave.open(str(path), "rb") as source:
                frames = source.getnframes()
                channels = source.getnchannels()
                width = source.getsampwidth()
                raw = source.readframes(frames)
        except (OSError, wave.Error):
            return []
        if width != 2 or not raw or not duration:
            return []
        sample_count = len(raw) // 2
        values = [
            int.from_bytes(raw[index : index + 2], "little", signed=True)
            for index in range(0, len(raw), 2)
        ]
        window_count = max(1, min(24, math.ceil(duration / 3)))
        result: list[float] = []
        for index in range(window_count):
            left = int(index * sample_count / window_count)
            right = int((index + 1) * sample_count / window_count)
            chunk = values[left * channels : right * channels] or [0]
            rms = math.sqrt(sum(value * value for value in chunk) / len(chunk)) / 32768
            result.append(min(1.0, rms * 4))
        peak = max(result) if result else 1
        return [value / peak if peak else 0.0 for value in result]
