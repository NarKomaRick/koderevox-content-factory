from pathlib import Path
from types import SimpleNamespace

from app.services.stt import FasterWhisperProvider


class FakeWhisperModel:
    def transcribe(self, _path: str, vad_filter: bool):
        assert vad_filter is True
        return (
            [
                SimpleNamespace(start=0.0, end=1.2, text=" Первая фраза "),
                SimpleNamespace(start=1.2, end=2.5, text="Вторая фраза"),
            ],
            SimpleNamespace(language="ru", duration=2.5),
        )


class FakeWordWhisperModel:
    def transcribe(
        self, _path: str, vad_filter: bool, word_timestamps: bool, initial_prompt: str | None
    ):
        assert vad_filter is True
        assert word_timestamps is True
        assert initial_prompt == "Koderevox, REST API"
        word = SimpleNamespace(word=" REST API ", start=0.2, end=0.9)
        segment = SimpleNamespace(start=0.0, end=1.0, text=" REST API ", words=[word])
        return [segment], SimpleNamespace(language="ru", duration=1.0)


async def test_faster_whisper_adapter_preserves_timestamps() -> None:
    provider = FasterWhisperProvider("small", "cuda", "float16")
    provider.model = FakeWhisperModel()

    result = await provider.transcribe(Path("audio.wav"))

    assert result.text == "Первая фраза Вторая фраза"
    assert result.language == "ru"
    assert result.duration == 2.5
    assert result.segments[1].start == 1.2


async def test_faster_whisper_preserves_word_timestamps_and_uses_vocabulary() -> None:
    provider = FasterWhisperProvider("small", "cpu", "int8")
    provider.model = FakeWordWhisperModel()

    result = await provider.transcribe(Path("audio.wav"), ["Koderevox", "REST API"])

    assert result.segments[0].words[0].word == "REST API"
    assert result.segments[0].words[0].start == 0.2
