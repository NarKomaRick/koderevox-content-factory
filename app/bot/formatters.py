from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def format_production(project: dict[str, Any]) -> str:
    script = project.get("approved_script_version_id") or project.get("current_script_version_id")
    return (
        f"🎬 {project.get('working_title') or project.get('title')}\n\n"
        f"Статус:\n{str(project.get('status', 'idea')).upper()}\n\n"
        f"Сценарий:\n{'✅' if project.get('approved_script_version_id') else '⚪'} "
        f"{str(script)[:8] if script else 'не создан'}\n\n"
        f"Озвучка:\n{'✅' if project.get('primary_voiceover_id') else '⚪ не загружена'}\n\n"
        f"Монтаж:\n{'✅' if project.get('active_timeline_revision_id') else '⚪ не создан'}"
    )


def format_angles(ideas: list[dict[str, Any]]) -> str:
    chunks = ["Выберите подход:"]
    for index, idea in enumerate(ideas, start=1):
        chunks.append(
            f"\n{index}. {idea['title']}\n"
            f"Hook: {idea['suggested_hook']}\n"
            f"Идея: {idea['description']}\n"
            f"Формат: {idea['suggested_format']} · ~{idea['estimated_duration']} сек."
        )
    return "\n".join(chunks)


def format_draft(draft: dict[str, Any]) -> str:
    scenes = "\n".join(
        f"{scene['start_second']}–{scene['end_second']} сек: {scene['spoken_text']}\n"
        f"На экране: {scene['on_screen']}"
        for scene in draft.get("scene_breakdown", [])
    )
    return (
        f"{draft['title']}\n\n"
        f"HOOK\n{draft['hook']}\n\n"
        f"СЦЕНАРИЙ\n{draft['script']}\n\n"
        f"СЦЕНЫ\n{scenes or '—'}\n\n"
        f"CAPTION\n{draft['caption']}\n\n"
        f"CTA\n{draft['call_to_action']}\n\n"
        f"Длительность: ~{draft.get('estimated_duration') or '—'} сек."
    )


def format_repurposed(drafts: list[dict[str, Any]]) -> list[str]:
    labels = {"youtube_shorts": "YouTube Short", "tiktok": "TikTok", "telegram": "Telegram"}
    return [
        f"{labels.get(item['platform'], item['platform'])}\n\n"
        f"{item['title']}\n\n{item['hook']}\n\n{item['script']}\n\n"
        f"Caption: {item['caption']}\nCTA: {item['call_to_action']}"
        for item in drafts
    ]


def format_inbox(page: dict[str, Any]) -> str:
    if not page["items"]:
        return "В Inbox пока нет материалов по этому фильтру."
    icons = {
        "voice": "🎤",
        "audio": "🎵",
        "video": "🎥",
        "video_note": "🎥",
        "image": "🖼",
        "document": "📄",
        "url": "🔗",
        "text": "📝",
    }
    lines = [f"📥 Content Inbox · страница {page['page']}/{page['pages']}"]
    for index, item in enumerate(page["items"], start=1):
        created = datetime.fromisoformat(item["created_at"]).astimezone().strftime("%d.%m, %H:%M")
        score = item.get("content_potential_score")
        score_text = f"🔥 {score}/100" if score is not None else "⏳"
        summary = (item.get("summary") or item.get("original_text") or "Обрабатывается")[:120]
        lines.append(
            f"\n{index}. {score_text}\n{icons.get(item['type'], '📥')} "
            f"{item.get('topic') or item.get('original_filename') or 'Новый материал'}\n"
            f'{created}\n"{summary}"'
        )
    return "\n".join(lines)


def format_source_detail(source: dict[str, Any]) -> str:
    analysis = source.get("content_analysis") or {}
    points = analysis.get("key_points", [])
    formats = analysis.get("recommended_formats", [])
    point_text = "\n".join(f"• {item}" for item in points) or "• Пока нет"
    format_text = "\n".join(f"• {item}" for item in formats) or "• Пока нет"
    score = source.get("content_potential_score")
    return (
        f"{source.get('topic') or source.get('original_filename') or 'Материал'}\n\n"
        f"Потенциал: {'🔥 ' + str(score) + '/100' if score is not None else 'ещё не оценён'}\n\n"
        f"Суть:\n{source.get('summary') or 'Материал ещё обрабатывается.'}\n\n"
        f"Ключевые моменты:\n{point_text}\n\n"
        f"Можно сделать:\n{format_text}"
    )


def format_digest(digest: dict[str, Any]) -> str:
    lines = [f"📊 Сегодня ты добавил {digest['total']} материалов.", "\nЛучшие:"]
    for item in digest["best"]:
        lines.append(
            f"🔥 {item.get('content_potential_score') or 0} — "
            f"{item.get('topic') or item.get('original_filename') or 'Материал'}"
        )
    counts = digest["recommended_format_counts"]
    if counts:
        lines.append("\nИз них можно сделать:")
        lines.extend(f"{count} × {name}" for name, count in counts.items())
    return "\n".join(lines)


def format_video_concepts(project: dict[str, Any]) -> str:
    lines = ["🎬 Нашёл 3 варианта Short:"]
    for index, concept in enumerate(project["concepts"], start=1):
        lines.append(
            f"\n{index}. {concept['title']}\n"
            f"Hook: {concept['hook']}\n"
            f"≈ {round(concept['target_duration'])} сек\n"
            f"Фокус: {concept['focus']}"
        )
    return "\n".join(lines)


def format_video_plan(project: dict[str, Any]) -> str:
    plan = project["edit_plan"]
    clips = plan.get("clips", [])
    duration = sum(item["source_end"] - item["source_start"] for item in clips)
    return (
        "✂️ План монтажа готов.\n\n"
        f"Клипов: {len(clips)}\n"
        f"≈ {duration:.1f} сек\n"
        f"Hook: {plan.get('hook_text', '—')}\n"
        f"Framing: {plan.get('framing', '—')}\n"
        f"Темп: {plan.get('pace', '—')}"
    )


def format_video_edit(project: dict[str, Any]) -> str:
    clips = project.get("edit_plan", {}).get("clips", [])
    if not clips:
        return "План монтажа ещё не создан."
    start = min(item["source_start"] for item in clips)
    end = max(item["source_end"] for item in clips)
    duration = sum(item["source_end"] - item["source_start"] for item in clips)
    return (
        f"Начало: {start:.1f} сек\n"
        f"Конец: {end:.1f} сек\n"
        f"Длина: {duration:.1f} сек\n"
        f"Клипов: {len(clips)}"
    )


def format_publication_preview(variants: list[dict[str, Any]]) -> str:
    labels = {"telegram": "Telegram", "youtube": "YouTube", "tiktok": "TikTok"}
    chunks = ["Готово к публикации. Тексты сохранены и не изменятся при запуске."]
    for item in variants:
        platform = labels.get(item["platform"], item["platform"])
        text = item.get("caption") or item.get("description") or "—"
        tags = " ".join(f"#{tag}" for tag in item.get("hashtags", []))
        settings = item.get("settings", {})
        platform_settings = ""
        if item["platform"] == "tiktok":
            platform_settings = (
                f"\nVisibility: {settings.get('privacy_level', 'не выбрана')}"
                f" · comments {'Off' if settings.get('disable_comment') else 'On'}"
                f" · duet {'Off' if settings.get('disable_duet') else 'On'}"
                f" · stitch {'Off' if settings.get('disable_stitch') else 'On'}"
            )
        chunks.append(
            f"\n{platform}\n{item.get('title') or '—'}\n{text}\n{tags}{platform_settings}".strip()
        )
    return "\n".join(chunks)


def format_publications(items: list[dict[str, Any]]) -> str:
    if not items:
        return "📅 Очередь публикаций пуста."
    icons = {
        "draft": "📝",
        "scheduled": "🕓",
        "queued": "⏳",
        "publishing": "🚀",
        "processing": "⏳",
        "published": "✅",
        "published_with_warning": "⚠️",
        "retry_wait": "🔄",
        "failed": "❌",
        "cancelled": "🚫",
    }
    lines = ["📅 Публикации"]
    for item in items[:20]:
        snapshot = item.get("variant_snapshot", {})
        scheduled = item.get("scheduled_at")
        timezone_name = item.get("publication_metadata", {}).get("timezone", "UTC")
        try:
            timezone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            timezone = ZoneInfo("UTC")
        when = (
            datetime.fromisoformat(scheduled).astimezone(timezone).strftime("%d.%m %H:%M")
            if scheduled
            else "сейчас"
        )
        lines.append(
            f"\n{icons.get(item['status'], '•')} {snapshot.get('title') or 'Без названия'}\n"
            f"{item['platform']} · {when} · {item['status']}\nID: {item['id']}"
        )
    return "\n".join(lines)
