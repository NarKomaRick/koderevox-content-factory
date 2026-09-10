from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StageDefinition:
    key: str
    label: str
    weight: float


PIPELINE_STAGES = (
    StageDefinition("producer", "Пишу сценарий", 0.30),
    StageDefinition("director", "Подбираю визуалы", 0.35),
    StageDefinition("render", "Собираю видео", 0.25),
    StageDefinition("publish", "Готовлю публикацию", 0.10),
)

STAGE_LABELS = {
    "understanding_goal": "Понимаю задачу",
    "researching": "Проверяю источники",
    "verifying": "Проверяю факты",
    "planning_angle": "Выбираю угол",
    "building_brief": "Собираю brief",
    "writing_script": "Пишу сценарий",
    "reviewing_script": "Проверяю сценарий",
    "planning_assets": "Планирую визуалы",
    "creating_production": "Передаю режиссёру",
    "analyzing_story": "Анализирую историю",
    "planning": "Планирую постановку",
    "assembling": "Собираю rough cut",
    "reviewing": "Проверяю монтаж",
    "correcting": "Исправляю найденное",
    "finalizing": "Финализирую видео",
    "render": "Рендерю видео",
    "publishing": "Готовлю публикацию",
    "waiting_approval": "Жду подтверждения",
}

JOB_STAGE_ORDERS = {
    "producer": (
        "understanding_goal",
        "researching",
        "verifying",
        "planning_angle",
        "building_brief",
        "writing_script",
        "reviewing_script",
        "planning_assets",
        "creating_production",
    ),
    "director": (
        "analyzing_story",
        "planning",
        "assembling",
        "reviewing",
        "correcting",
        "finalizing",
    ),
}


def label_for(stage: str, fallback: str | None = None) -> str:
    return STAGE_LABELS.get(stage, fallback or stage.replace("_", " ").capitalize())
