import uuid

import pytest
from sqlalchemy import select

from app.core.config import Settings
from app.director.runtime import DirectorRuntime
from app.director.tools import (
    DirectorToolError,
    DirectorToolRegistry,
    EmptyArguments,
    ToolDefinition,
)
from app.models import ProductionProject, Project, SourceItem, User, VisualAsset
from app.models.enums import AssetStatus, AssetType, SourceStatus, SourceType, UserRole


def test_registry_rejects_unknown_tools_and_invalid_arguments() -> None:
    registry = DirectorToolRegistry([ToolDefinition("inspect", "Inspect", EmptyArguments)])

    with pytest.raises(DirectorToolError, match="Unknown Director tool"):
        registry.get("shell")
    with pytest.raises(DirectorToolError):
        registry.parse("inspect", {"unexpected": True})


@pytest.mark.asyncio
async def test_runtime_enforces_project_isolation(session) -> None:
    project = await session.scalar(select(Project))
    user = User(telegram_id=uuid.uuid4().int % 10**9, role=UserRole.USER)
    other_project = Project(name="Other project")
    session.add_all([user, other_project])
    await session.flush()
    source = SourceItem(
        project_id=project.id,
        user_id=user.id,
        type=SourceType.TEXT,
        original_text="source",
        processing_status=SourceStatus.READY,
    )
    session.add(source)
    await session.flush()
    production = ProductionProject(
        project_id=project.id,
        user_id=user.id,
        initial_source_item_id=source.id,
        title="Production",
    )
    foreign_asset = VisualAsset(
        project_id=other_project.id,
        type=AssetType.IMAGE,
        status=AssetStatus.READY,
        original_path="image.jpg",
        filename="image.jpg",
        mime_type="image/jpeg",
        file_size=10,
    )
    session.add_all([production, foreign_asset])
    await session.commit()

    runtime = DirectorRuntime(session, production.id, Settings(video_font_path=""))
    result = await runtime.execute(
        "add_visual",
        {"asset_id": str(foreign_asset.id), "start": 0, "end": 2},
    )

    assert not result.ok
    assert result.error is not None
    assert result.error["code"] == "ASSET_OUTSIDE_PROJECT"
