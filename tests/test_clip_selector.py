from app.ai.mock import MockAIProvider
from app.models import Project, SourceItem
from app.models.enums import SourceType
from app.schemas.video import EditPlan, VideoConcept
from app.services.clip_selector import LLMClipSelector
from app.services.edit_plan import EditPlanValidator


class InvalidThenValidAI:
    def __init__(self) -> None:
        self.calls = 0
        self.prompts: list[str] = []

    async def generate_structured(self, *, system_prompt, user_prompt, response_model):
        self.calls += 1
        self.prompts.append(user_prompt)
        if self.calls == 1:
            return response_model.model_validate(
                {
                    "clips": [
                        {
                            "source_start": 0,
                            "source_end": 12,
                            "source_segment_ids": [99],
                            "purpose": "main",
                        }
                    ],
                    "hook_text": "Ошибка",
                    "recommended_duration": 12,
                    "reasoning_summary": "Невалидный ответ",
                    "framing": "center_crop",
                    "pace": "medium",
                }
            )
        return await MockAIProvider().generate_structured(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            response_model=response_model,
        )


async def test_clip_selector_retries_impossible_timestamp_plan() -> None:
    source = SourceItem(
        project_id=Project().id,
        user_id=Project().id,
        type=SourceType.VIDEO,
        local_file_path="source.mp4",
        duration_seconds=12.5,
        transcript="Сегодня обнаружили проблему. 1С получала две записи.",
        transcript_segments=[
            {"start": 0, "end": 5.2, "text": "Сегодня обнаружили проблему."},
            {"start": 5.2, "end": 12.5, "text": "1С получала две записи."},
        ],
    )
    brand = Project(
        name="Koderevox",
        brand_context="Инженерная студия",
        target_audience="Разработчики",
        language="ru",
    )
    concept = VideoConcept(
        title="История бага",
        hook="Два запроса",
        focus="Разбор фактической причины",
        target_duration=12,
    )
    provider = InvalidThenValidAI()
    selector = LLMClipSelector(provider)  # type: ignore[arg-type]

    result = await selector.edit_plan(
        source,
        brand,
        concept,
        EditPlanValidator(minimum_duration=2),
        instruction="Оставь только техническую часть",
    )

    assert isinstance(result.plan, EditPlan)
    assert result.attempts == 2
    assert provider.calls == 2
    assert "nonexistent transcript segment" in provider.prompts[1]
    assert "Оставь только техническую часть" in provider.prompts[1]


def test_video_prompt_never_sends_media_bytes() -> None:
    from app.ai.prompts.video_editing import build_video_concepts_prompt

    source = SourceItem(
        project_id=Project().id,
        user_id=Project().id,
        type=SourceType.VIDEO,
        local_file_path="secret-client-video.mp4",
        transcript="Только фактическая речь",
        transcript_segments=[],
    )
    prompt = build_video_concepts_prompt(source)
    assert "Только фактическая речь" in prompt
    assert "secret-client-video.mp4" not in prompt
    assert "Do not invent" in prompt
