from app.models import ContentIdea


def build_short_script_prompt(idea: ContentIdea) -> str:
    return f"""Создай полноценный сценарий YouTube Short длительностью 25–60 секунд.
Текст должен быть написан для живой речи разработчика. Первые 1–3 секунды — сильный,
но честный hook. Дай сцены с таймингом, произносимым текстом и тем, что показывать на экране.
Структура должна служить мысли, а не выглядеть механическим шаблоном.

Название: {idea.title}
Подход: {idea.angle}
Описание: {idea.description}
Предложенный hook: {idea.suggested_hook}
Аудитория: {idea.target_audience}
"""
