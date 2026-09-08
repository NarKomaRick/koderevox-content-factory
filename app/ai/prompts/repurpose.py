from app.models import ContentDraft, ContentIdea


def build_repurpose_prompt(idea: ContentIdea, draft: ContentDraft) -> str:
    return f"""Адаптируй материал в три самостоятельные версии:
1) YouTube Short: ясный технический сценарий 25–60 секунд.
2) TikTok: допустим близкий смысл, но hook и caption адаптируй под платформу.
3) Telegram post: не транскрипт ролика, а подробный пост с заголовком, вводной,
основной мыслью, техническими подробностями, выводом и мягким CTA при необходимости.

Идея: {idea.title}
Угол: {idea.angle}
Исходный сценарий:
{draft.script}
"""
