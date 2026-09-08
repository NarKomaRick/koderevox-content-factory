from app.bot.access import is_user_allowed


def test_allowed_telegram_user() -> None:
    assert is_user_allowed(100, {100, 200}) is True


def test_unknown_telegram_user_is_denied() -> None:
    assert is_user_allowed(999, {100, 200}) is False
