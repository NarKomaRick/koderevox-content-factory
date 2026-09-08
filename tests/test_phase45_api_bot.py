from types import SimpleNamespace

import pytest

from app.bot.formatters import format_production
from app.bot.handlers import setup_ai_connection
from app.bot.keyboards import main_menu, production_keyboard, setup_keyboard
from app.main import app


def test_phase45_openapi_exposes_production_and_setup_workflows() -> None:
    paths = app.openapi()["paths"]
    expected = {
        "/production-projects": "post",
        "/production-projects/{production_project_id}": "get",
        "/production-projects/{production_project_id}/materials": "post",
        "/production-projects/{production_project_id}/scripts/generate": "post",
        "/production-projects/{production_project_id}/scripts/edit": "post",
        "/production-projects/{production_project_id}/voiceovers/{source_item_id}": "post",
        "/production-projects/{production_project_id}/assembly": "post",
        "/production-projects/{production_project_id}/placement": "post",
        "/production-projects/materials/{material_id}/placement": "post",
        "/production-projects/{production_project_id}/replan": "post",
        "/production-projects/{production_project_id}/timeline-revisions": "get",
        "/production-projects/{production_project_id}/render/{profile}": "post",
        "/setup/summary": "get",
        "/setup/diagnostics": "get",
        "/setup/runtime-setting": "patch",
        "/setup/secret": "post",
        "/setup/ai/test-and-activate": "post",
    }
    for path, method in expected.items():
        assert method in paths[path]


def test_main_menu_production_view_and_controls() -> None:
    labels = [button.text for row in main_menu().keyboard for button in row]
    assert "🎬 Новый ролик" in labels
    assert "📂 Мои ролики" in labels
    project = {
        "id": "project-id",
        "title": "Технический ролик",
        "working_title": "Технический ролик",
        "status": "rough_cut",
        "approved_script_version_id": "script-id",
        "primary_voiceover_id": "voice-id",
        "active_timeline_revision_id": "revision-id",
    }
    text = format_production(project)
    assert "ROUGH_CUT" in text and "Озвучка" in text
    callbacks = [
        button.callback_data
        for row in production_keyboard(project).inline_keyboard
        for button in row
    ]
    assert any(value.startswith("prod_assemble:") for value in callbacks)
    assert any(value.startswith("prod_final:") for value in callbacks)
    assert setup_keyboard().inline_keyboard[-1][0].callback_data == "setup:diagnostics"


class FakeMessage:
    def __init__(self) -> None:
        self.from_user = SimpleNamespace(id=42)
        self.text = "http://lm.test/v1 | qwen | top-secret-value"
        self.deleted = False
        self.answers: list[str] = []

    async def delete(self) -> None:
        self.deleted = True

    async def answer(self, text: str) -> None:
        self.answers.append(text)


class FakeState:
    def __init__(self) -> None:
        self.cleared = False

    async def clear(self) -> None:
        self.cleared = True


class FakeBackend:
    def __init__(self) -> None:
        self.key_seen: str | None = None

    async def setup_ai(self, **data):
        self.key_seen = data["api_key"]
        return {"latency_ms": 12}


@pytest.mark.asyncio
async def test_setup_secret_message_deletion_is_attempted_and_fsm_cleared() -> None:
    message = FakeMessage()
    state = FakeState()
    backend = FakeBackend()
    await setup_ai_connection(message, state, backend)  # type: ignore[arg-type]
    assert backend.key_seen == "top-secret-value"
    assert message.deleted is True
    assert state.cleared is True
    assert all("top-secret-value" not in answer for answer in message.answers)
