import logging

from app.core.logging import silence_sensitive_transport_logs


def test_sensitive_http_transport_logs_are_suppressed() -> None:
    logging.getLogger("httpx").setLevel(logging.INFO)
    logging.getLogger("httpcore").setLevel(logging.INFO)

    silence_sensitive_transport_logs()

    assert logging.getLogger("httpx").level == logging.WARNING
    assert logging.getLogger("httpcore").level == logging.WARNING
