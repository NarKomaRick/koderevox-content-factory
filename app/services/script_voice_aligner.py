import re
from difflib import SequenceMatcher
from typing import Any

from app.schemas.production import AlignmentRange, ScriptAlignment


def _tokens(text: str) -> list[str]:
    return re.findall(r"[\w+#.]+", text.casefold(), flags=re.UNICODE)


class ScriptVoiceAligner:
    """Monotonic fuzzy alignment that tolerates paraphrases and missing/extra speech."""

    def align(
        self,
        structured_sections: list[dict[str, Any]],
        words: list[dict[str, Any]],
        transcript: str,
        *,
        duration: float,
    ) -> ScriptAlignment:
        normalized_words = self._usable_words(words, transcript, duration)
        sections = [
            (str(item.get("id") or f"section_{index}"), str(item.get("text") or "").strip())
            for index, item in enumerate(structured_sections, start=1)
            if str(item.get("text") or "").strip()
        ]
        if not sections:
            sections = [("section_1", transcript)]
        if len(normalized_words) < len(sections):
            # Very poor STT can yield fewer timestamped words than semantic sections.
            # Keep a monotonic low-confidence timeline instead of crashing the pipeline.
            spoken = _tokens(transcript) or ["unrecognized"]
            step = max(duration, 0.1) / len(sections)
            normalized_words = [
                {
                    "word": spoken[index % len(spoken)],
                    "start": index * step,
                    "end": (index + 1) * step,
                }
                for index in range(len(sections))
            ]
        total_script_tokens = max(1, sum(len(_tokens(text)) for _, text in sections))
        cursor = 0
        aligned: list[AlignmentRange] = []
        unmatched: list[str] = []
        for index, (section_id, section_text) in enumerate(sections):
            target = max(
                1, round(len(_tokens(section_text)) / total_script_tokens * len(normalized_words))
            )
            remaining_sections = len(sections) - index - 1
            maximum_end = max(cursor + 1, len(normalized_words) - remaining_sections)
            best: tuple[float, int, int, str] | None = None
            start_min = cursor
            start_max = min(maximum_end - 1, cursor + max(2, target // 2))
            for start in range(start_min, start_max + 1):
                for length in range(max(1, target // 2), max(2, target * 2) + 1):
                    end = min(maximum_end, start + length)
                    if end <= start:
                        continue
                    voice_text = " ".join(str(item["word"]) for item in normalized_words[start:end])
                    similarity = self.similarity(section_text, voice_text)
                    length_penalty = abs(length - target) / max(target, 1) * 0.08
                    score = similarity - length_penalty
                    if best is None or score > best[0]:
                        best = (score, start, end, voice_text)
            assert best is not None
            _, start_index, end_index, voice_text = best
            confidence = self.similarity(section_text, voice_text)
            start_time = float(normalized_words[start_index]["start"])
            end_time = float(normalized_words[end_index - 1]["end"])
            aligned.append(
                AlignmentRange(
                    section_id=section_id,
                    script_text=section_text,
                    voice_text=voice_text,
                    start=start_time,
                    end=max(start_time + 0.01, end_time),
                    confidence=round(confidence, 4),
                )
            )
            if confidence < 0.35:
                unmatched.append(section_text)
            cursor = end_index
        extra = " ".join(str(item["word"]) for item in normalized_words[cursor:]).strip()
        weights = [max(0.01, item.end - item.start) for item in aligned]
        overall = sum(
            item.confidence * weight for item, weight in zip(aligned, weights, strict=True)
        ) / sum(weights)
        return ScriptAlignment(
            sections=aligned,
            overall_confidence=round(overall, 4),
            unmatched_script=unmatched,
            extra_spoken=[extra] if extra else [],
        )

    @staticmethod
    def similarity(left: str, right: str) -> float:
        left_tokens, right_tokens = _tokens(left), _tokens(right)
        if not left_tokens or not right_tokens:
            return 0.0
        sequence = SequenceMatcher(None, left_tokens, right_tokens).ratio()
        left_set, right_set = set(left_tokens), set(right_tokens)
        overlap = len(left_set & right_set) / max(1, len(left_set | right_set))
        # Character similarity helps Russian morphology; token overlap rewards exact terminology.
        chars = SequenceMatcher(None, " ".join(left_tokens), " ".join(right_tokens)).ratio()
        return min(1.0, sequence * 0.45 + overlap * 0.25 + chars * 0.30)

    @staticmethod
    def _usable_words(
        words: list[dict[str, Any]], transcript: str, duration: float
    ) -> list[dict[str, Any]]:
        valid = [
            item
            for item in words
            if str(item.get("word") or "").strip()
            and item.get("start") is not None
            and item.get("end") is not None
            and float(item["end"]) > float(item["start"])
        ]
        if valid:
            return valid
        tokens = _tokens(transcript) or ["тишина"]
        step = max(duration, 0.1) / len(tokens)
        return [
            {"word": token, "start": index * step, "end": (index + 1) * step}
            for index, token in enumerate(tokens)
        ]
