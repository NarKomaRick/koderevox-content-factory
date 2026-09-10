"""Confidence-weighted preference signals, separate from model training."""

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DirectorPreference


class DirectorPreferences:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(
        self, *, owner_id: uuid.UUID | None = None, project_id: uuid.UUID | None = None
    ) -> dict[str, dict[str, Any]]:
        scopes = []
        if project_id:
            scopes.append(("project", project_id))
        if owner_id:
            scopes.append(("user", owner_id))
        result: dict[str, dict[str, Any]] = {}
        for scope, value in scopes:
            column = (
                DirectorPreference.project_id if scope == "project" else DirectorPreference.owner_id
            )
            rows = await self.session.scalars(
                select(DirectorPreference).where(DirectorPreference.scope == scope, column == value)
            )
            for item in rows:
                result[item.key] = {
                    "value": item.value,
                    "confidence": item.confidence,
                    "evidence_count": item.evidence_count,
                    "scope": scope,
                }
        return result

    async def record(
        self,
        key: str,
        value: str,
        *,
        scope: str = "project",
        owner_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        strength: float = 0.15,
    ) -> DirectorPreference:
        if scope not in {"project", "user", "brand"}:
            raise ValueError("unsupported preference scope")
        filters = [DirectorPreference.scope == scope, DirectorPreference.key == key]
        filters.extend(
            [
                DirectorPreference.owner_id == owner_id
                if owner_id is not None
                else DirectorPreference.owner_id.is_(None),
                DirectorPreference.project_id == project_id
                if project_id is not None
                else DirectorPreference.project_id.is_(None),
            ]
        )
        query = select(DirectorPreference).where(*filters)
        item = await self.session.scalar(query)
        if item is None:
            item = DirectorPreference(
                scope=scope,
                owner_id=owner_id,
                project_id=project_id,
                key=key,
                value=value[:512],
                confidence=min(1.0, max(0.0, strength)),
                evidence_count=1,
            )
            self.session.add(item)
        else:
            item.value = value[:512]
            item.confidence = min(1.0, item.confidence + strength * (1 - item.confidence))
            item.evidence_count += 1
        await self.session.flush()
        return item
