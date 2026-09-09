from app.models import ContentIdea


def build_telegram_post_prompt(idea: ContentIdea, source_text: str) -> str:
    return f"""Создай самостоятельный Telegram-пост для технической аудитории.
Это не транскрипт ролика: нужен ясный заголовок, сильная вводная, основная мысль,
технические подробности, вывод и мягкий CTA только если он уместен.
Не добавляй факты, которых нет в исходном материале. Пиши по-русски, чисто и без AI-клише.

Тема: {idea.title}
Угол: {idea.angle}
Исходный материал:
{source_text}
"""
