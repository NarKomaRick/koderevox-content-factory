"""Bounded Director agent loop with structured fallback for local OpenAI-compatible models."""

import uuid
from typing import Any, Protocol

import structlog
from sqlalchemy import select

from app.ai.base import AIProvider
from app.core.config import Settings
from app.director.prompts import DIRECTOR_SYSTEM_PROMPT, build_director_user_prompt
from app.director.runtime import DirectorRuntime
from app.director.schemas import (
    DirectorToolCall,
    DirectorToolResult,
    DirectorTurn,
    ModelCapabilityProfile,
)
from app.models import DirectorAction, DirectorRun
from app.progress import ProgressReporter
from app.services.errors import InvalidStateError

logger = structlog.get_logger()


class DirectorModel(Protocol):
    capabilities: ModelCapabilityProfile

    async def next_turn(
        self,
        *,
        context: dict[str, Any],
        tools: list[dict[str, Any]],
        instruction: str,
        history: list[dict[str, Any]],
    ) -> DirectorTurn: ...


class StructuredDirectorModel:
    """Adapts the existing AIProvider to the Director structured fallback protocol."""

    def __init__(self, provider: AIProvider) -> None:
        self.provider = provider
        self.capabilities = ModelCapabilityProfile(
            supports_tools=False,
            supports_vision=False,
            supports_video=False,
            supports_json_schema=True,
            max_context=8192,
        )

    async def next_turn(
        self,
        *,
        context: dict[str, Any],
        tools: list[dict[str, Any]],
        instruction: str,
        history: list[dict[str, Any]],
    ) -> DirectorTurn:
        prompt = build_director_user_prompt(context, tools, instruction)
        return await self.provider.generate_structured(
            system_prompt=DIRECTOR_SYSTEM_PROMPT, user_prompt=prompt, response_model=DirectorTurn
        )


def create_director_model(settings: Settings, provider: AIProvider) -> DirectorModel:
    return (
        FakeDirectorModel() if settings.ai_provider == "mock" else StructuredDirectorModel(provider)
    )


class FakeDirectorModel:
    """Deterministic test model: inspect → select clip/asset → text → preview → final."""

    def __init__(self) -> None:
        self.turn = 0
        self.capabilities = ModelCapabilityProfile(max_context=8192)

    async def next_turn(
        self,
        *,
        context: dict[str, Any],
        tools: list[dict[str, Any]],
        instruction: str,
        history: list[dict[str, Any]],
    ) -> DirectorTurn:
        self.turn += 1
        duration = float(
            context.get("voiceover", {}).get("duration", 0)
            or context.get("timeline", {}).get("duration", 0)
            or 5
        )
        assets = context.get("assets", [])
        if self.turn == 1:
            return DirectorTurn(
                reasoning="Inspect the bounded project context first.",
                tool_calls=[
                    DirectorToolCall(id="inspect", name="inspect_project"),
                    DirectorToolCall(id="assets", name="list_assets"),
                ],
            )
        if self.turn == 2:
            calls: list[DirectorToolCall] = []
            visual = next(
                (item for item in assets if item.get("type") == "video"),
                assets[0] if assets else None,
            )
            if visual:
                calls.append(
                    DirectorToolCall(
                        id="clip-search",
                        name="find_clip",
                        arguments={
                            "asset_id": visual["id"],
                            "description": "relevant technical scene",
                            "preferred_duration": 4,
                        },
                    )
                )
                calls.append(
                    DirectorToolCall(
                        id="visual",
                        name="add_visual",
                        arguments={
                            "asset_id": visual["id"],
                            "start": 0.5,
                            "end": min(duration, 4.5),
                            "source_start": 2,
                            "source_end": 5,
                            "layout": "fullscreen",
                        },
                    )
                )
            calls.append(
                DirectorToolCall(
                    id="title",
                    name="add_text",
                    arguments={
                        "text": "Смысл важнее шума",
                        "start": 0.5,
                        "end": min(duration, 3.5),
                        "anchor": "top_center",
                        "style": "accent",
                    },
                )
            )
            calls.append(
                DirectorToolCall(
                    id="graphic",
                    name="add_graphic",
                    arguments={
                        "kind": "stat_card",
                        "start": 5,
                        "end": min(duration, 8),
                        "content": {"value": "API", "label": "stable contract"},
                    },
                )
            )
            return DirectorTurn(
                reasoning="Select a concrete clip and add readable supporting visuals.",
                tool_calls=calls,
            )
        if self.turn == 3:
            return DirectorTurn(
                reasoning="Use the safe blur layout on the selected footage.",
                tool_calls=[
                    DirectorToolCall(
                        id="blur",
                        name="blur_region",
                        arguments={
                            "start": 1,
                            "end": min(duration, 4),
                            "mode": "background_blur",
                        },
                    )
                ],
            )
        if self.turn == 4:
            return DirectorTurn(
                reasoning="Render an inexpensive preview before finalizing.",
                tool_calls=[DirectorToolCall(id="preview", name="render_preview")],
            )
        if self.turn == 5:
            return DirectorTurn(
                reasoning="Run hard validators.",
                tool_calls=[DirectorToolCall(id="validate", name="validate_timeline")],
            )
        return DirectorTurn(
            reasoning="The bounded fake workflow is complete.",
            tool_calls=[DirectorToolCall(id="finalize", name="finalize")],
        )


class DirectorAgent:
    def __init__(
        self, runtime: DirectorRuntime, model: DirectorModel, settings: Settings | None = None
    ) -> None:
        self.runtime = runtime
        self.model = model
        self.settings = settings or runtime.settings

    async def run(self, run: DirectorRun) -> DirectorRun:
        if run.production_project_id != self.runtime.production_project_id:
            raise InvalidStateError("Director run is outside the runtime project")
        run.status = "running"
        run.active = True
        await self.runtime.session.commit()
        progress = ProgressReporter(
            self.runtime.session,
            "director",
            run.id,
            source_kind="fake" if self.settings.ai_provider == "mock" else "production",
            director_run_id=run.id,
            production_project_id=run.production_project_id,
            min_delta=self.settings.progress_min_percent_delta,
            min_interval_seconds=self.settings.progress_update_interval_seconds,
        )
        await progress.report_stage(
            "director",
            step_index=0,
            step_total=self.settings.director_max_steps,
            message="Director начинает работу",
            force=True,
        )
        try:
            for step in range(self.settings.director_max_steps):
                run.step_count = step + 1
                if run.llm_call_count >= self.settings.director_max_llm_calls:
                    raise InvalidStateError("Director LLM call limit reached")
                context = await self.runtime.context()
                tools = self.runtime.registry.openai_tools()
                await logger.ainfo("director_llm_call", run_id=str(run.id), step=step + 1)
                turn = await self.model.next_turn(
                    context=context,
                    tools=tools,
                    instruction=run.instruction,
                    history=run.history_json or [],
                )
                run.llm_call_count += 1
                if not turn.tool_calls:
                    if turn.finalize:
                        turn = DirectorTurn(
                            reasoning=turn.reasoning,
                            tool_calls=[DirectorToolCall(id=f"finalize-{step}", name="finalize")],
                        )
                    else:
                        raise InvalidStateError("Director returned no tool call")
                for call in turn.tool_calls:
                    result = await self._execute_once(run, call, step + 1)
                    if result.data.get("revision_id"):
                        run.current_revision_id = uuid.UUID(str(result.data["revision_id"]))
                    if not result.ok and call.name == "finalize":
                        run.history_json = [
                            *(run.history_json or []),
                            {"tool": call.name, "result": result.model_dump(mode="json")},
                        ]
                        continue
                    if call.name == "finalize" and result.ok:
                        run.status = "completed"
                        run.active = False
                        run.best_revision_id = run.current_revision_id
                        await self.runtime.session.commit()
                        await progress.complete(message="Director завершил работу")
                        return run
                run.history_json = [
                    *(run.history_json or []),
                    {"step": step + 1, "reasoning": turn.reasoning[:1000]},
                ]
                await self.runtime.session.commit()
            raise InvalidStateError("Director step limit reached")
        except Exception as exc:
            run.status = "failed"
            run.active = False
            run.error = str(exc)[:2000]
            await self.runtime.session.commit()
            await progress.fail(error_code=type(exc).__name__, message=str(exc)[:2000])
            await logger.aerror(
                "director_completed",
                run_id=str(run.id),
                status="failed",
                error_type=type(exc).__name__,
            )
            return run

    async def _execute_once(
        self, run: DirectorRun, call: DirectorToolCall, step: int
    ) -> DirectorToolResult:
        existing = await self.runtime.session.scalar(
            select(DirectorAction).where(
                DirectorAction.run_id == run.id, DirectorAction.tool_call_id == call.id
            )
        )
        if existing is not None:
            return DirectorToolResult.model_validate(existing.result)
        result = await self.runtime.execute(call.name, call.arguments, run=run, step=step)
        action = DirectorAction(
            run_id=run.id,
            tool_call_id=call.id,
            step_number=step,
            tool_name=call.name,
            arguments=call.arguments,
            result=result.model_dump(mode="json"),
            revision_id=uuid.UUID(str(result.data["revision_id"]))
            if result.data.get("revision_id")
            else None,
        )
        self.runtime.session.add(action)
        await self.runtime.session.flush()
        return result
