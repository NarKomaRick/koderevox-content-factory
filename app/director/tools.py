"""Strict tool registry exposed to the Director model."""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from app.director.policies import DirectorToolError


class EmptyArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    description: str
    arguments_model: type[BaseModel]

    def as_openai_tool(self) -> dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.arguments_model.model_json_schema(),
            },
        }


class DirectorToolRegistry:
    def __init__(self, definitions: list[ToolDefinition] | None = None) -> None:
        self._definitions = {item.name: item for item in definitions or []}

    def register(self, definition: ToolDefinition) -> None:
        if definition.name in self._definitions:
            raise ValueError(f"Director tool already registered: {definition.name}")
        self._definitions[definition.name] = definition

    def get(self, name: str) -> ToolDefinition:
        try:
            return self._definitions[name]
        except KeyError as exc:
            raise DirectorToolError("UNKNOWN_TOOL", f"Unknown Director tool: {name}") from exc

    def parse(self, name: str, arguments: dict[str, Any]) -> BaseModel:
        definition = self.get(name)
        try:
            payload = dict(arguments)
            if "operation" in definition.arguments_model.model_fields:
                payload.setdefault("operation", "add_visual" if name == "add_image" else name)
            return definition.arguments_model.model_validate(payload)
        except ValidationError as exc:
            raise DirectorToolError("INVALID_TOOL_ARGUMENTS", str(exc)) from exc

    def names(self) -> tuple[str, ...]:
        return tuple(self._definitions)

    def openai_tools(self) -> list[dict[str, Any]]:
        return [item.as_openai_tool() for item in self._definitions.values()]


ToolRegistry = DirectorToolRegistry
