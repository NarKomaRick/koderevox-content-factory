from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ContentChannelProfile, DirectorPreference, ProducerRun, Project


class ProducerPreferenceResolver:
    """Reads the existing DirectorPreference store using the producer namespace."""

    PREFIX = "producer."
    PRIORITY = ("explicit", "campaign", "project", "channel", "brand", "learned", "default")

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def resolve(
        self,
        *,
        project_id: uuid.UUID,
        user_id: uuid.UUID | None = None,
        platform: str = "youtube_shorts",
        explicit: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        project = await self.session.get(Project, project_id)
        channel = await self.session.scalar(
            select(ContentChannelProfile).where(
                ContentChannelProfile.project_id == project_id,
                ContentChannelProfile.platform == platform,
            )
        )
        rows = (
            await self.session.scalars(
                select(DirectorPreference).where(
                    or_(
                        DirectorPreference.project_id == project_id,
                        DirectorPreference.owner_id == user_id,
                    ),
                    DirectorPreference.key.like(f"{self.PREFIX}%"),
                )
            )
        ).all()
        result: dict[str, Any] = dict(defaults or {})
        if project:
            result.setdefault("audience", project.target_audience)
            result.setdefault("brand_voice", project.brand_context)
            result.setdefault("tone", (project.brand_preset or {}).get("tone", ""))
        if channel:
            if channel.audience:
                result["audience"] = channel.audience
            if channel.tone:
                result["tone"] = channel.tone
            if channel.preferred_duration:
                result["preferred_duration"] = channel.preferred_duration
            if channel.cta_strategy:
                result["cta_strategy"] = channel.cta_strategy
        for row in sorted(
            rows,
            key=lambda item: (
                self.PRIORITY.index(item.scope)
                if item.scope in self.PRIORITY
                else len(self.PRIORITY)
            ),
            reverse=True,
        ):
            result[row.key.removeprefix(self.PREFIX)] = row.value
        result.update(explicit or {})
        return result


async def content_history(
    session: AsyncSession, project_id: uuid.UUID, *, exclude_run_id: uuid.UUID | None = None
) -> list[str]:
    query = select(ProducerRun).where(ProducerRun.project_id == project_id)
    if exclude_run_id:
        query = query.where(ProducerRun.id != exclude_run_id)
    rows = (await session.scalars(query.order_by(ProducerRun.created_at.desc()).limit(100))).all()
    result: list[str] = []
    for row in rows:
        angle = row.artifacts.get("angle", {})
        result.extend(
            [str(angle.get("title", "")), str(angle.get("core_message", "")), row.raw_prompt]
        )
    return [item for item in result if item]
