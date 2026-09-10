from __future__ import annotations

import asyncio
from collections import defaultdict

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_LOCAL_LOCKS: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)


class OperationsTickLock:
    """Best-effort distributed lock with a deterministic SQLite fallback."""

    def __init__(self, session: AsyncSession, key: str = "content-factory:operations-tick") -> None:
        self.session = session
        self.key = key
        self._local = _LOCAL_LOCKS[key]
        self._database_acquired = False
        self._local_acquired = False

    async def acquire(self) -> bool:
        if self._local.locked():
            return False
        await self._local.acquire()
        self._local_acquired = True
        bind = self.session.get_bind()
        if bind.dialect.name != "postgresql":
            return True
        result = await self.session.execute(
            text("SELECT pg_try_advisory_lock(hashtext(:lock_key))"),
            {"lock_key": self.key},
        )
        self._database_acquired = bool(result.scalar())
        if not self._database_acquired:
            self._release_local()
        return self._database_acquired

    async def release(self) -> None:
        if self._database_acquired:
            await self.session.execute(
                text("SELECT pg_advisory_unlock(hashtext(:lock_key))"),
                {"lock_key": self.key},
            )
            self._database_acquired = False
        self._release_local()

    def _release_local(self) -> None:
        if self._local_acquired:
            self._local.release()
            self._local_acquired = False

    async def __aenter__(self) -> bool:
        return await self.acquire()

    async def __aexit__(self, _exc_type: object, _exc: object, _traceback: object) -> None:
        await self.release()
