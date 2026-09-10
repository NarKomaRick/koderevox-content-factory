import pytest

from app.operations.locking import OperationsTickLock


@pytest.mark.asyncio
async def test_operations_tick_lock_serializes_concurrent_local_ticks(session) -> None:
    first = OperationsTickLock(session, key="test:operations-lock")
    second = OperationsTickLock(session, key="test:operations-lock")

    assert await first.acquire() is True
    assert await second.acquire() is False
    await first.release()

    assert await second.acquire() is True
    await second.release()
