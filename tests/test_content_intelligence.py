import pytest
from pydantic import ValidationError

from app.ai.prompts.content_intelligence import build_content_intelligence_prompt
from app.schemas.ai import ContentIntelligence


def test_incomplete_context_is_limited_to_three_questions() -> None:
    intelligence = ContentIntelligence(
        topic="Проблема с авторизацией",
        summary="Авторизацию исправили, но детали неизвестны.",
        source_facts=["Проблему с авторизацией исправили"],
        key_points=[],
        interesting_details=[],
        ai_suggestions=["Уточнить техническую причину"],
        content_angles=[],
        content_pillars=["case"],
        target_audiences=["Разработчики"],
        content_potential_score=45,
        why_it_is_interesting="Может стать кейсом после уточнений.",
        recommended_formats=["short_video"],
        requires_more_context=True,
        questions_to_user=["Что ломалось?", "В чём причина?", "Как исправили?"],
    )
    assert intelligence.requires_more_context is True
    assert len(intelligence.questions_to_user) == 3

    with pytest.raises(ValidationError):
        payload = intelligence.model_dump()
        payload["questions_to_user"] = ["1", "2", "3", "4"]
        ContentIntelligence.model_validate(payload)


def test_prompt_forbids_invented_facts_and_defines_score() -> None:
    prompt = build_content_intelligence_prompt("Мы нашли баг с двойными запросами")

    assert "Никогда не добавляй в факты придуманные" in prompt
    assert "0–20" in prompt
    assert "81–100" in prompt
    assert "максимум три" in prompt
