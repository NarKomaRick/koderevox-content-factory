from datetime import UTC, datetime, timedelta

from app.services.retry_policy import RetryPolicy


def test_provider_neutral_retry_policy_is_bounded_and_schedules_backoff() -> None:
    now = datetime(2026, 9, 14, 9, tzinfo=UTC)
    policy = RetryPolicy(max_attempts=3, delays_seconds=[60, 300], jitter_ratio=0)

    first = policy.decide_for(1, retryable=True, now=now)
    second = policy.decide_for(2, retryable=True, now=now)
    exhausted = policy.decide_for(3, retryable=True, now=now)
    permanent = policy.decide_for(1, retryable=False, now=now)

    assert first.retry_at == now + timedelta(seconds=60)
    assert second.retry_at == now + timedelta(seconds=300)
    assert exhausted.retry is False
    assert permanent.retry is False
