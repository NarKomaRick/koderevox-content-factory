import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_allowed_user_ids_accept_comma_separated_env(monkeypatch) -> None:
    monkeypatch.setenv("TELEGRAM_ALLOWED_USER_IDS", "123, 456")

    settings = Settings(_env_file=None)

    assert settings.telegram_allowed_user_ids == [123, 456]


def test_phase3_render_settings_are_validated() -> None:
    settings = Settings(_env_file=None, video_width=1080, video_height=1920)
    assert settings.celery_render_concurrency == 1

    with pytest.raises(ValidationError):
        Settings(_env_file=None, video_width=1079)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, video_min_duration=80, video_max_duration=60)
