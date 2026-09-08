import asyncio
from pathlib import Path
from typing import Any

from app.schemas.processing import TranscriptionResult, TranscriptSegment, TranscriptWord


class FasterWhisperProvider:
    """Optional STT adapter. Install the `stt` extra before using it."""

    def __init__(
        self, model_name: str = "small", device: str = "cpu", compute_type: str = "int8"
    ) -> None:
        self.model_name = model_name
        self.device = device
        self.compute_type = compute_type
        self.model: Any | None = None

    def _get_model(self) -> Any:
        if self.model is not None:
            return self.model
        try:
            from faster_whisper import WhisperModel  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError("faster-whisper is not installed") from exc
        self.model = WhisperModel(
            self.model_name, device=self.device, compute_type=self.compute_type
        )
        return self.model

    async def transcribe(
        self, media_path: Path, vocabulary: list[str] | None = None
    ) -> TranscriptionResult:
        return await asyncio.to_thread(self._transcribe_sync, media_path, vocabulary)

    def _transcribe_sync(
        self, media_path: Path, vocabulary: list[str] | None = None
    ) -> TranscriptionResult:
        initial_prompt = ", ".join(vocabulary) if vocabulary else None
        model = self._get_model()
        try:
            raw_segments, info = model.transcribe(
                str(media_path),
                vad_filter=True,
                word_timestamps=True,
                initial_prompt=initial_prompt,
            )
        except TypeError:
            # Keeps compatibility with older faster-whisper-compatible adapters.
            raw_segments, info = model.transcribe(str(media_path), vad_filter=True)
        segments = [
            TranscriptSegment(
                start=item.start,
                end=item.end,
                text=item.text.strip(),
                words=[
                    TranscriptWord(word=word.word.strip(), start=word.start, end=word.end)
                    for word in (getattr(item, "words", None) or [])
                    if word.start is not None and word.end is not None and word.word.strip()
                ],
            )
            for item in raw_segments
        ]
        return TranscriptionResult(
            text=" ".join(item.text for item in segments).strip(),
            language=getattr(info, "language", None),
            duration=getattr(info, "duration", None),
            segments=segments,
        )
