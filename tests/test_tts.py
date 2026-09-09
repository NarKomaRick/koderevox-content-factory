from pathlib import Path

import pytest

from app.services.tts import EspeakTTSProvider


@pytest.mark.asyncio
async def test_espeak_tts_returns_valid_audio(tmp_path: Path) -> None:
    result = await EspeakTTSProvider(rate=125).synthesize(
        "Проверка локальной озвучки для видеоредактора.",
        tmp_path / "voice.wav",
    )
    assert result.provider == "espeak"
    assert result.language == "ru"
    assert result.duration > 0
    assert result.sample_rate > 0
    assert result.path.stat().st_size > 0


@pytest.mark.asyncio
async def test_tts_rejects_empty_text(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        await EspeakTTSProvider().synthesize(" ", tmp_path / "voice.wav")
