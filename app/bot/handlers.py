import base64
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx
import structlog
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.filters.state import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import BufferedInputFile, CallbackQuery, Message, Update

from app.bot.api_client import BackendClient
from app.bot.formatters import (
    format_angles,
    format_digest,
    format_draft,
    format_inbox,
    format_production,
    format_publication_preview,
    format_publications,
    format_repurposed,
    format_source_detail,
    format_video_concepts,
    format_video_edit,
    format_video_plan,
)
from app.bot.ingestion import build_source_payload, received_message
from app.bot.keyboards import (
    angle_keyboard,
    approved_video_keyboard,
    develop_idea_keyboard,
    draft_keyboard,
    inbox_keyboard,
    main_menu,
    platform_selection_keyboard,
    production_keyboard,
    production_list_keyboard,
    publication_detail_keyboard,
    publication_preview_keyboard,
    publication_time_keyboard,
    publications_filter_keyboard,
    script_version_keyboard,
    setup_keyboard,
    source_detail_keyboard,
    thumbnail_keyboard,
    tiktok_settings_keyboard,
    video_concepts_keyboard,
    video_edit_keyboard,
    video_plan_keyboard,
    video_style_keyboard,
    video_text_keyboard,
    visual_suggestions_keyboard,
)

logger = structlog.get_logger()
router = Router()


class IdeaFlow(StatesGroup):
    waiting_for_text = State()
    choosing_angle = State()


class SourceContextFlow(StatesGroup):
    waiting_for_note = State()
    waiting_for_voice_note = State()


class VideoEditFlow(StatesGroup):
    waiting_for_instruction = State()
    waiting_for_subtitle_replacement = State()
    waiting_for_manual_range = State()
    waiting_for_thumbnail_text = State()
    waiting_for_visual_manual = State()
    waiting_for_visual_instruction = State()


class AssetFlow(StatesGroup):
    waiting_for_material = State()


class PublishingFlow(StatesGroup):
    selecting_platforms = State()
    editing_variant = State()
    waiting_for_time = State()
    waiting_for_datetime = State()
    waiting_for_reschedule = State()
    editing_publication = State()


class ProductionFlow(StatesGroup):
    waiting_for_idea = State()
    active = State()
    waiting_for_script_edit = State()
    waiting_for_replan = State()


class ProducerFlow(StatesGroup):
    waiting_for_prompt = State()


class SetupFlow(StatesGroup):
    waiting_for_ai = State()


@router.message(F.text == "✨ Создать ролик")
async def new_producer_run(message: Message, state: FSMContext) -> None:
    await state.set_state(ProducerFlow.waiting_for_prompt)
    await message.answer("Опишите ролик одним сообщением — я исследую тему и подготовлю сценарий.")


@router.message(ProducerFlow.waiting_for_prompt, F.text)
async def receive_producer_prompt(
    message: Message, state: FSMContext, backend: BackendClient
) -> None:
    if message.from_user is None:
        return
    try:
        run = await backend.create_producer_run(
            telegram_user_id=message.from_user.id,
            prompt=message.text or "",
            idempotency_key=f"telegram:{message.from_user.id}:{message.message_id}",
        )
    except httpx.HTTPError as exc:
        await logger.aexception("telegram_producer_flow_failed", error_type=type(exc).__name__)
        await message.answer("Не удалось создать Producer run. Проверьте, включён ли Producer.")
        return
    await state.clear()
    await message.answer(f"✅ Producer run created: {run['id']}\n🔎 Исследую тему")


@router.message(F.text == "🎬 Новый ролик")
async def new_production(message: Message, state: FSMContext) -> None:
    await state.set_state(ProductionFlow.waiting_for_idea)
    await message.answer("О чём хочешь сделать ролик? Можно отправить текст, voice, URL или файл.")


@router.message(F.text == "📂 Мои ролики")
async def my_productions(message: Message, backend: BackendClient) -> None:
    assert message.from_user is not None
    projects = await backend.list_productions(message.from_user.id)
    if not projects:
        await message.answer("Роликов пока нет. Нажмите «🎬 Новый ролик».")
        return
    await message.answer("📂 Мои ролики", reply_markup=production_list_keyboard(projects))


@router.message(
    ProductionFlow.waiting_for_idea,
    F.content_type.in_({"text", "voice", "audio", "video", "video_note", "photo", "document"}),
)
async def receive_production_idea(
    message: Message, event_update: Update, state: FSMContext, backend: BackendClient
) -> None:
    payload = build_source_payload(message, event_update.update_id)
    result = await backend.ingest(payload)
    source = result["source"]
    title = message.text or message.caption or source.get("original_filename") or "Новый ролик"
    project = await backend.create_production(source, title)
    await state.set_state(ProductionFlow.active)
    await state.update_data(production_id=project["id"])
    await message.answer(format_production(project), reply_markup=production_keyboard(project))


@router.callback_query(F.data.startswith("prod_open:"))
async def open_production(
    callback: CallbackQuery, state: FSMContext, backend: BackendClient
) -> None:
    await callback.answer()
    if not callback.data or not isinstance(callback.message, Message):
        return
    project = await backend.get_production(callback.data.split(":", 1)[1])
    await state.set_state(ProductionFlow.active)
    await state.update_data(production_id=project["id"])
    await callback.message.answer(
        format_production(project), reply_markup=production_keyboard(project)
    )


@router.callback_query(F.data.startswith("prod_script:"))
async def production_script(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if not callback.data or not isinstance(callback.message, Message):
        return
    project_id = callback.data.split(":", 1)[1]
    script = await backend.generate_production_script(project_id)
    await callback.message.answer(
        f"📝 Сценарий v{script['version_number']}\n\n{script['content']}",
        reply_markup=script_version_keyboard(project_id, script["id"]),
    )


@router.callback_query(F.data.startswith("prod_develop:"))
async def develop_production_idea(callback: CallbackQuery) -> None:
    await callback.answer()
    if callback.data and isinstance(callback.message, Message):
        project_id = callback.data.split(":", 1)[1]
        await callback.message.answer(
            "🧠 Как развить идею? Research работает через прикреплённые источники и "
            "подтверждённые факты; внешний search provider опционален.",
            reply_markup=develop_idea_keyboard(project_id),
        )


@router.callback_query(F.data.startswith("prod_develop_add:"))
async def develop_production_add(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.data and isinstance(callback.message, Message):
        _, project_id, action = callback.data.split(":", 2)
        prompts = {
            "thoughts": "Отправьте дополнительные мысли любым сообщением.",
            "facts": "Отправьте факт вместе со ссылкой или документом-источником.",
            "gaps": "Добавьте контекст; система учтёт его при следующей версии сценария.",
            "expand": "Отправьте материал, которым нужно расширить идею.",
        }
        await state.set_state(ProductionFlow.active)
        await state.update_data(production_id=project_id)
        await callback.message.answer(prompts.get(action, "Отправьте дополнительный материал."))


@router.callback_query(F.data.startswith("prod_script_edit:"))
async def request_production_script_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.data and isinstance(callback.message, Message):
        project_id = callback.data.split(":", 1)[1]
        await state.set_state(ProductionFlow.waiting_for_script_edit)
        await state.update_data(production_id=project_id)
        await callback.message.answer("Напишите правку обычным языком.")


@router.callback_query(F.data.startswith("prod_hook:"))
async def strengthen_production_hook(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if callback.data and isinstance(callback.message, Message):
        project_id = callback.data.split(":", 1)[1]
        script = await backend.edit_production_script(
            project_id, "Начало слишком скучное. Усиль hook."
        )
        await callback.message.answer(
            f"📝 Сценарий v{script['version_number']}\n\n{script['content']}",
            reply_markup=script_version_keyboard(project_id, script["id"]),
        )


@router.message(ProductionFlow.waiting_for_script_edit, F.text)
async def apply_production_script_edit(
    message: Message, state: FSMContext, backend: BackendClient
) -> None:
    project_id = str((await state.get_data()).get("production_id") or "")
    script = await backend.edit_production_script(project_id, message.text or "")
    await state.set_state(ProductionFlow.active)
    await message.answer(
        f"📝 Сценарий v{script['version_number']}\n\n"
        f"Изменения: {', '.join(script.get('diff', {}).get('summary', []))}\n\n"
        f"{script['content']}",
        reply_markup=script_version_keyboard(project_id, script["id"]),
    )


@router.callback_query(F.data.startswith("prod_approve:"))
async def approve_production_script(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer("Сценарий утверждён")
    if callback.data and isinstance(callback.message, Message):
        token = callback.data.split(":", 1)[1]
        decoded = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        project_id = str(uuid.UUID(bytes=decoded[:16]))
        script_id = str(uuid.UUID(bytes=decoded[16:32]))
        await backend.approve_production_script(project_id, script_id)
        await callback.message.answer(
            "✅ Сценарий утверждён. Дальше отправьте финальную озвучку через «Добавить материал»."
        )


@router.callback_query(F.data.startswith("prod_add:"))
async def add_production_material(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.data and isinstance(callback.message, Message):
        await state.set_state(ProductionFlow.active)
        await state.update_data(production_id=callback.data.split(":", 1)[1])
        await callback.message.answer(
            "Отправьте text, voice, audio, photo, video, screenshot, document или URL. "
            "Caption станет инструкцией по использованию."
        )


@router.message(
    ProductionFlow.active,
    F.content_type.in_({"text", "voice", "audio", "video", "video_note", "photo", "document"}),
)
async def receive_production_material(
    message: Message, event_update: Update, state: FSMContext, backend: BackendClient
) -> None:
    project_id = str((await state.get_data()).get("production_id") or "")
    payload = build_source_payload(message, event_update.update_id)
    result = await backend.ingest(payload)
    project = await backend.get_production(project_id)
    is_audio = payload["type"] in {"voice", "audio", "video_note"}
    roles = ["voiceover"] if is_audio and project.get("approved_script_version_id") else []
    await backend.attach_production_material(
        project_id,
        source_item_id=result["source"]["id"],
        roles=roles,
        instruction=message.caption or (message.text if payload["type"] != "text" else None),
    )
    if roles:
        await message.answer("🎙 Озвучка принята. STT и alignment выполняются в media worker.")
    else:
        await message.answer("📎 Материал привязан к текущему ролику и обрабатывается.")


@router.callback_query(F.data.startswith("prod_materials:"))
async def production_materials(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if callback.data and isinstance(callback.message, Message):
        items = await backend.production_materials(callback.data.split(":", 1)[1])
        used = sum(bool(item["is_used"]) for item in items)
        lines = [f"📎 Материалы: {len(items)} · используется: {used}"]
        lines.extend(
            f"{'✅' if item['is_used'] else '⚪'} {', '.join(item['roles']) or 'обработка'}"
            for item in items[:20]
        )
        await callback.message.answer("\n".join(lines))


@router.callback_query(F.data.startswith("prod_assemble:"))
async def assemble_production(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if callback.data and isinstance(callback.message, Message):
        revision = await backend.assemble_production(callback.data.split(":", 1)[1])
        await callback.message.answer(
            f"🎬 Черновой монтаж готов. Timeline revision {revision['revision_number']}."
        )


@router.callback_query(F.data.startswith("prod_autodirector:"))
async def run_autonomous_director(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if callback.data and isinstance(callback.message, Message):
        production_id = callback.data.split(":", 1)[1]
        result = await backend.run_autonomous_director(
            production_id,
            "Сделай ролик понятным, технологичным и динамичным. Поддержи историю "
            "конкретными визуалами и проверь preview перед финалом.",
        )
        await callback.message.answer(
            f"🧠 Автодиректор запущен. Run {result['id']} · статус: {result['status']}"
        )


@router.callback_query(F.data.startswith("prod_place:"))
async def select_production_placement(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer("Место выбрано")
    if callback.data and isinstance(callback.message, Message):
        _, material_id, index = callback.data.split(":", 2)
        result = await backend.select_production_placement(material_id, int(index))
        await callback.message.answer(
            f"✅ Locked-вставка добавлена в Timeline revision {result['revision']}."
        )


@router.callback_query(F.data.startswith("prod_preview:"))
@router.callback_query(F.data.startswith("prod_final:"))
async def render_production(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if callback.data and isinstance(callback.message, Message):
        action, project_id = callback.data.split(":", 1)
        profile = "final" if action == "prod_final" else "preview"
        result = await backend.render_production(project_id, profile)
        await callback.message.answer(f"Рендер {profile} поставлен в очередь: {result['task_id']}")


@router.callback_query(F.data.startswith("prod_replan:"))
async def request_production_replan(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.data and isinstance(callback.message, Message):
        await state.set_state(ProductionFlow.waiting_for_replan)
        await state.update_data(production_id=callback.data.split(":", 1)[1])
        await callback.message.answer("Опишите, какой участок и как изменить.")


@router.message(ProductionFlow.waiting_for_replan, F.text)
async def apply_production_replan(
    message: Message, state: FSMContext, backend: BackendClient
) -> None:
    project_id = str((await state.get_data()).get("production_id") or "")
    revision = await backend.replan_production(project_id, message.text or "")
    await state.set_state(ProductionFlow.active)
    await message.answer(
        f"✅ Создан Timeline revision {revision['revision_number']}. "
        "Ручные locked-вставки сохранены."
    )


@router.message(Command("setup"))
@router.message(F.text == "⚙️ Настройки")
async def setup_menu(message: Message) -> None:
    if message.chat.type != "private":
        await message.answer("Настройки доступны только в private chat.")
        return
    await message.answer(
        "⚙️ Настройки\n\nРазделы с внешними credentials активируются после bootstrap "
        "APP_MASTER_KEY и INITIAL_OWNER_TELEGRAM_ID.",
        reply_markup=setup_keyboard(),
    )


@router.callback_query(F.data.startswith("setup:"))
async def setup_section(callback: CallbackQuery, state: FSMContext, backend: BackendClient) -> None:
    await callback.answer()
    if isinstance(callback.message, Message) and callback.data:
        section = callback.data.split(":", 1)[1]
        if section == "ai":
            await state.set_state(SetupFlow.waiting_for_ai)
            await callback.message.answer(
                "Отправьте одной строкой: BASE_URL | MODEL | API_KEY\n"
                "Для LM Studio API_KEY можно оставить пустым. Сообщение будет удалено."
            )
            return
        if section == "diagnostics" and callback.from_user:
            diagnostics = await backend.setup_diagnostics(callback.from_user.id)
            await callback.message.answer(
                "📊 Диагностика\n\n"
                + "\n".join(f"{name:<18} {value}" for name, value in diagnostics.items())
            )
            return
        descriptions = {
            "ai": (
                "🤖 AI: LM Studio / OpenAI-compatible. Provider test обязателен перед activation."
            ),
            "stt": "🎙 STT: faster-whisper; model/device/compute доступны как runtime settings.",
            "brand": "🎨 Бренд: Koderevox technical / clean / dark / minimal.",
            "render": "⚙️ Render: PREVIEW 720×1280, FINAL 1080×1920.",
            "security": "🔐 Secrets: encrypted database store; master key только из ENV.",
            "diagnostics": "📊 Диагностика доступна через API; secret values никогда не выводятся.",
        }
        await callback.message.answer(descriptions.get(section, "Not configured"))


@router.message(SetupFlow.waiting_for_ai, F.text)
async def setup_ai_connection(message: Message, state: FSMContext, backend: BackendClient) -> None:
    assert message.from_user is not None
    parts = [part.strip() for part in (message.text or "").split("|")]
    if len(parts) != 3 or not parts[0] or not parts[1]:
        await message.answer("Формат: BASE_URL | MODEL | API_KEY")
        return
    base_url, model, api_key = parts
    try:
        result = await backend.setup_ai(
            telegram_user_id=message.from_user.id,
            base_url=base_url,
            model=model,
            api_key=api_key or None,
        )
    except httpx.HTTPError:
        await message.answer("⚠️ Подключение не прошло проверку. Конфигурация не активирована.")
        return
    finally:
        try:
            await message.delete()
        except Exception as exc:
            await logger.awarning(
                "telegram_secret_message_delete_failed", error_type=type(exc).__name__
            )
        await state.clear()
    await message.answer(
        f"🔐 Ключ сохранён.\n✅ Подключение работает.\nModel: {model}\n"
        f"Latency: {result['latency_ms']} ms"
    )


@router.message(CommandStart())
async def start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("AI Content Factory готова. Что сделаем?", reply_markup=main_menu())


@router.message(Command("inbox"))
@router.message(F.text == "📥 Контент-инбокс")
async def show_inbox(message: Message, backend: BackendClient) -> None:
    assert message.from_user is not None
    page = await backend.list_inbox(message.from_user.id)
    await message.answer(
        format_inbox(page),
        reply_markup=inbox_keyboard(page["items"], page["page"], page["pages"]),
    )


@router.message(Command("search"))
async def search_inbox(message: Message, backend: BackendClient) -> None:
    assert message.from_user is not None
    query = (message.text or "").partition(" ")[2].strip()
    if not query:
        await message.answer("Использование: /search запрос")
        return
    page = await backend.list_inbox(message.from_user.id, query=query)
    await message.answer(
        format_inbox(page),
        reply_markup=inbox_keyboard(page["items"], page["page"], page["pages"]),
    )


@router.message(Command("digest"))
async def daily_digest(message: Message, backend: BackendClient) -> None:
    assert message.from_user is not None
    digest = await backend.digest(message.from_user.id)
    await message.answer(format_digest(digest))


@router.message(F.text == "➕ Новая идея")
async def new_idea(message: Message, state: FSMContext) -> None:
    await state.set_state(IdeaFlow.waiting_for_text)
    await message.answer("Отправьте мысль одним сообщением.")


@router.message(F.text == "📎 Добавить материалы")
async def request_asset(message: Message, state: FSMContext) -> None:
    await state.set_state(AssetFlow.waiting_for_material)
    await message.answer(
        "Отправьте screenshot, photo, screen recording, logo, UI, код или видео. "
        "Комментарий в caption станет описанием. Проект по умолчанию — Koderevox."
    )


@router.message(F.text == "🗂 Материалы")
async def show_assets(message: Message, backend: BackendClient) -> None:
    projects = await backend.list_projects()
    if not projects:
        await message.answer("Сначала создайте проект.")
        return
    project = next((item for item in projects if item["name"] == "Koderevox"), projects[0])
    assets = await backend.list_assets(project["id"])
    if not assets:
        await message.answer("🗂 В Asset Library пока нет материалов.")
        return
    lines = ["🗂 Материалы"]
    for index, asset in enumerate(assets[:10], start=1):
        dimensions = f"{asset.get('width') or '—'}×{asset.get('height') or '—'}"
        lines.append(
            f"\n{index}. {asset['title']}\n{asset['type']} · {dimensions}\n"
            f"Tags: {', '.join(asset.get('tags') or []) or '—'}"
        )
    await message.answer("\n".join(lines))


@router.message(
    AssetFlow.waiting_for_material,
    F.content_type.in_({"video", "photo", "document"}),
)
async def receive_asset(
    message: Message, event_update: Update, state: FSMContext, backend: BackendClient
) -> None:
    payload = build_source_payload(message, event_update.update_id)
    await backend.ingest(payload)
    await state.clear()
    await message.answer("📎 Материал принят. После processing он появится в Asset Library.")


@router.message(IdeaFlow.waiting_for_text, F.text)
async def receive_idea(message: Message, state: FSMContext, backend: BackendClient) -> None:
    assert message.from_user is not None
    wait_message = await message.answer("Сохраняю мысль и готовлю три разных подхода…")
    try:
        source = await backend.create_text_source(
            telegram_user_id=message.from_user.id,
            telegram_username=message.from_user.username,
            text=message.text or "",
        )
        ideas = await backend.generate_ideas(source["id"])
        await state.update_data(source_id=source["id"])
        await state.set_state(IdeaFlow.choosing_angle)
        await wait_message.edit_text(format_angles(ideas), reply_markup=angle_keyboard(ideas))
    except httpx.HTTPError as exc:
        await logger.aexception("telegram_idea_flow_failed", error_type=type(exc).__name__)
        await wait_message.edit_text("Не удалось сгенерировать варианты. Попробуйте ещё раз.")


@router.callback_query(F.data.startswith("idea:"))
async def choose_angle(callback: CallbackQuery, state: FSMContext, backend: BackendClient) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or callback.data is None:
        return
    message = callback.message
    idea_id = callback.data.split(":", maxsplit=1)[1]
    await message.edit_text("Генерирую сценарий Short…")
    try:
        draft = await backend.generate_draft(idea_id)
        await state.clear()
        await message.edit_text(format_draft(draft), reply_markup=draft_keyboard(draft["id"]))
    except httpx.HTTPError as exc:
        await logger.aexception("telegram_draft_flow_failed", error_type=type(exc).__name__)
        await message.edit_text("Не удалось сгенерировать сценарий.")


@router.callback_query(IdeaFlow.choosing_angle, F.data == "ideas:more")
async def more_angles(callback: CallbackQuery, state: FSMContext, backend: BackendClient) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    message = callback.message
    source_id = (await state.get_data()).get("source_id")
    if not source_id:
        await message.edit_text("Сессия истекла. Начните с «Новая идея».")
        return
    await message.edit_text("Готовлю ещё три подхода…")
    ideas = await backend.generate_ideas(str(source_id))
    await message.edit_text(format_angles(ideas), reply_markup=angle_keyboard(ideas))


@router.callback_query(F.data == "ideas:cancel")
async def cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    await state.clear()
    if isinstance(callback.message, Message):
        await callback.message.edit_text("Отменено.")


@router.callback_query(F.data.startswith("approve:"))
async def approve(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer("Одобрено")
    if callback.data:
        await backend.approve(callback.data.split(":", 1)[1])
    if isinstance(callback.message, Message):
        await callback.message.answer("Сценарий одобрен ✅")


@router.callback_query(F.data.startswith("regen:"))
async def regenerate(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or callback.data is None:
        return
    message = callback.message
    await message.edit_text("Генерирую новую версию…")
    draft = await backend.regenerate(callback.data.split(":", 1)[1])
    await message.edit_text(format_draft(draft), reply_markup=draft_keyboard(draft["id"]))


@router.callback_query(F.data.startswith("repurpose:"))
async def repurpose(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or callback.data is None:
        return
    message = callback.message
    await message.answer("Адаптирую для трёх платформ…")
    drafts = await backend.repurpose(callback.data.split(":", 1)[1])
    for text in format_repurposed(drafts):
        await message.answer(text)


@router.callback_query(F.data.startswith("delete:"))
async def delete_draft(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if callback.data:
        await backend.delete_draft(callback.data.split(":", 1)[1])
    if isinstance(callback.message, Message):
        await callback.message.edit_text("Черновик удалён.")


@router.callback_query(F.data.startswith("inbox:"))
async def paginate_inbox(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or not callback.data or not callback.from_user:
        return
    _, filter_name, raw_page = callback.data.split(":", maxsplit=2)
    source_type = filter_name if filter_name in {"voice", "video", "text", "url"} else None
    page = await backend.list_inbox(
        callback.from_user.id,
        page=int(raw_page),
        source_type=source_type,
        best=filter_name == "best",
    )
    await callback.message.edit_text(
        format_inbox(page),
        reply_markup=inbox_keyboard(page["items"], page["page"], page["pages"], filter_name),
    )


@router.callback_query(F.data.startswith("source_open:"))
async def open_source(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or not callback.data:
        return
    source = await backend.get_source(callback.data.split(":", 1)[1])
    await callback.message.edit_text(
        format_source_detail(source),
        reply_markup=source_detail_keyboard(
            source["id"], video=source["type"] in {"video", "video_note"}
        ),
    )


@router.callback_query(F.data.startswith("source_short:"))
async def source_short(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or not callback.data:
        return
    source_id = callback.data.split(":", 1)[1]
    try:
        source = await backend.get_source(source_id)
        if source["type"] in {"video", "video_note"}:
            progress = await callback.message.answer("🎬 Анализирую видео…")
            project = await backend.create_video_project(source_id)
            await progress.edit_text(
                format_video_concepts(project),
                reply_markup=video_concepts_keyboard(project["id"]),
            )
            return
        await callback.message.answer("Готовлю Short из материала…")
        draft = await backend.generate_source_short(source_id)
        await callback.message.answer(format_draft(draft), reply_markup=draft_keyboard(draft["id"]))
    except httpx.HTTPError as exc:
        await logger.aexception("telegram_short_flow_failed", error_type=type(exc).__name__)
        await callback.message.answer("Не удалось подготовить Short. Исходный материал сохранён.")


@router.callback_query(F.data.startswith("video_concept:"))
async def choose_video_concept(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or not callback.data:
        return
    _, project_id, raw_index = callback.data.split(":", maxsplit=2)
    await callback.message.edit_text("✂️ Готовлю проверяемый план монтажа…")
    try:
        project = await backend.generate_video_edit_plan(project_id, int(raw_index))
        await callback.message.edit_text(
            format_video_plan(project), reply_markup=video_plan_keyboard(project["id"])
        )
    except httpx.HTTPError as exc:
        await logger.aexception("telegram_edit_plan_failed", error_type=type(exc).__name__)
        await callback.message.edit_text("Не удалось построить корректный план монтажа.")


@router.callback_query(F.data.startswith("video_more:"))
async def more_video_concepts(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or not callback.data:
        return
    project = await backend.regenerate_video_concepts(callback.data.split(":", 1)[1])
    await callback.message.edit_text(
        format_video_concepts(project), reply_markup=video_concepts_keyboard(project["id"])
    )


@router.callback_query(F.data.startswith("video_custom:"))
@router.callback_query(F.data.startswith("video_instruction:"))
@router.callback_query(F.data.startswith("video_add:"))
@router.callback_query(F.data.startswith("video_remove:"))
async def request_video_instruction(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or not callback.data:
        return
    await state.set_state(VideoEditFlow.waiting_for_instruction)
    await state.update_data(video_project_id=callback.data.split(":", 1)[1])
    await callback.message.answer(
        "Напишите пожелание к монтажу, например: «оставь только техническую часть» "
        "или «сделай до 30 секунд»."
    )


@router.message(VideoEditFlow.waiting_for_instruction, F.text)
async def apply_video_instruction(
    message: Message, state: FSMContext, backend: BackendClient
) -> None:
    project_id = (await state.get_data()).get("video_project_id")
    if not project_id:
        await state.clear()
        return
    current = await backend.get_video_project(str(project_id))
    concept_index = current.get("selected_concept")
    if concept_index is None:
        concept_index = 0
    project = await backend.generate_video_edit_plan(
        str(project_id), int(concept_index), message.text or ""
    )
    await state.clear()
    await message.answer(
        format_video_plan(project), reply_markup=video_plan_keyboard(project["id"])
    )


@router.callback_query(F.data.startswith("video_render:"))
@router.callback_query(F.data.startswith("video_rerender:"))
async def render_video(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or not callback.data:
        return
    action, project_id = callback.data.split(":", 1)
    try:
        response = await backend.render_video(project_id, force=action == "video_rerender")
        text = (
            "⚙️ Собираю ролик…" if response["queued"] else "Этот рендер уже готов или выполняется."
        )
        await callback.message.answer(text)
    except httpx.HTTPError as exc:
        await logger.aexception("telegram_render_enqueue_failed", error_type=type(exc).__name__)
        await callback.message.answer("Не удалось запустить рендер. План монтажа сохранён.")


@router.callback_query(F.data.startswith("video_visuals:"))
async def suggest_video_visuals(
    callback: CallbackQuery, state: FSMContext, backend: BackendClient
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or not callback.data:
        return
    project_id = callback.data.split(":", 1)[1]
    plan = await backend.suggest_visuals(project_id)
    await state.update_data(visual_suggestion=plan, video_project_id=project_id)
    lines = [f"🤖 Нашёл {len(plan['insertions'])} подходящие вставки:"]
    for index, item in enumerate(plan["insertions"], start=1):
        lines.append(
            f"\n{index}. {item['start']:.1f}–{item['end']:.1f}\n{item['role']} · {item['layout']}"
        )
    await callback.message.answer(
        "\n".join(lines), reply_markup=visual_suggestions_keyboard(project_id)
    )


@router.callback_query(F.data.startswith("visual_apply:"))
async def apply_visuals(callback: CallbackQuery, state: FSMContext, backend: BackendClient) -> None:
    await callback.answer("Применено")
    if not callback.data or not isinstance(callback.message, Message):
        return
    project_id = callback.data.split(":", 1)[1]
    plan = (await state.get_data()).get("visual_suggestion")
    if plan:
        await backend.set_visual_plan(project_id, plan)
    await callback.message.answer("VisualPlan сохранён. Нажмите «Пересобрать».")


@router.callback_query(F.data.startswith("visual_none:"))
async def remove_all_visuals(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if callback.data and isinstance(callback.message, Message):
        project_id = callback.data.split(":", 1)[1]
        await backend.set_visual_plan(
            project_id,
            {"insertions": [], "reasoning_summary": "user disabled"},
        )
        await callback.message.answer("Ролик останется без B-roll.")


@router.callback_query(F.data.startswith("visual_manual:"))
async def request_manual_visual(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.data and isinstance(callback.message, Message):
        await state.set_state(VideoEditFlow.waiting_for_visual_manual)
        await state.update_data(video_project_id=callback.data.split(":", 1)[1])
        await callback.message.answer(
            "Формат: asset UUID | 00:12-00:16 | fullscreen. "
            "Layouts: fullscreen, picture_in_picture, side_by_side, device_frame, code_card."
        )


@router.message(VideoEditFlow.waiting_for_visual_manual, F.text)
async def add_manual_visual(message: Message, state: FSMContext, backend: BackendClient) -> None:
    project_id = (await state.get_data()).get("video_project_id")
    try:
        raw_asset, raw_range, layout = [part.strip() for part in (message.text or "").split("|")]
        raw_start, raw_end = raw_range.split("-", 1)
        start, end = _timestamp_seconds(raw_start), _timestamp_seconds(raw_end)
        if end <= start:
            raise ValueError
    except ValueError:
        await message.answer("Не понял. Пример: UUID | 00:12-00:16 | fullscreen")
        return
    await backend.add_visual(
        str(project_id),
        {
            "asset_id": raw_asset,
            "start": start,
            "end": end,
            "layout": layout,
            "role": "manual",
            "reason": "user selected",
            "required": True,
        },
    )
    await state.clear()
    await message.answer("Visual добавлен как обязательный. Пересоберите ролик.")


@router.callback_query(F.data.startswith("visual_instruction:"))
async def request_visual_instruction(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.data and isinstance(callback.message, Message):
        await state.set_state(VideoEditFlow.waiting_for_visual_instruction)
        await state.update_data(video_project_id=callback.data.split(":", 1)[1])
        await callback.message.answer(
            "Напишите: «Убери второй скрин», «Не показывай код» "
            "или «Сделай screen recording на весь экран»."
        )


@router.message(VideoEditFlow.waiting_for_visual_instruction, F.text)
async def apply_visual_instruction(
    message: Message, state: FSMContext, backend: BackendClient
) -> None:
    project_id = (await state.get_data()).get("video_project_id")
    await backend.edit_visuals(str(project_id), message.text or "")
    await state.clear()
    await message.answer("VisualPlan обновлён без изменения EditPlan.")


@router.callback_query(F.data.startswith("video_thumbnail:"))
@router.callback_query(F.data.startswith("thumb_more:"))
async def show_thumbnails(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if not callback.data or not isinstance(callback.message, Message):
        return
    project_id = callback.data.split(":", 1)[1]
    items = await backend.generate_thumbnails(project_id)
    lines = ["🖼 Три варианта обложки:"]
    lines.extend(f"{index}. {item['concept']['headline']}" for index, item in enumerate(items, 1))
    for index, item in enumerate(items, start=1):
        preview = await backend.download_thumbnail(item["id"])
        await callback.message.answer_photo(
            BufferedInputFile(preview, filename=f"cover-{index}.jpg"),
            caption=f"{index}. {item['concept']['headline']}",
        )
    await callback.message.answer(
        "\n".join(lines), reply_markup=thumbnail_keyboard(items, project_id)
    )


@router.callback_query(F.data.startswith("thumb_select:"))
async def select_thumbnail(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer("Выбрано")
    if callback.data and isinstance(callback.message, Message):
        await backend.select_thumbnail(callback.data.split(":", 1)[1])
        await callback.message.answer("Обложка выбрана ✅")


@router.callback_query(F.data.startswith("thumb_custom:"))
async def request_custom_thumbnail(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.data and isinstance(callback.message, Message):
        await state.set_state(VideoEditFlow.waiting_for_thumbnail_text)
        await state.update_data(video_project_id=callback.data.split(":", 1)[1])
        await callback.message.answer("Введите заголовок обложки: 2–6 точных слов.")


@router.message(VideoEditFlow.waiting_for_thumbnail_text, F.text)
async def custom_thumbnail(message: Message, state: FSMContext, backend: BackendClient) -> None:
    project_id = (await state.get_data()).get("video_project_id")
    if not project_id:
        await state.clear()
        return
    items = await backend.generate_thumbnails(str(project_id), message.text or "")
    await state.clear()
    preview = await backend.download_thumbnail(items[0]["id"])
    await message.answer_photo(
        BufferedInputFile(preview, filename="cover-custom.jpg"),
        caption=items[0]["concept"]["headline"],
        reply_markup=thumbnail_keyboard(items, str(project_id)),
    )


@router.callback_query(F.data.startswith("video_approve:"))
async def approve_video(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer("Одобрено")
    if callback.data:
        await backend.approve_video(callback.data.split(":", 1)[1])
    if isinstance(callback.message, Message):
        video_project_id = callback.data.split(":", 1)[1] if callback.data else ""
        await callback.message.answer(
            "Видео одобрено ✅", reply_markup=approved_video_keyboard(video_project_id)
        )


@router.callback_query(F.data.startswith("video_publish:"))
async def choose_publish_platforms(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.data or not isinstance(callback.message, Message):
        return
    video_project_id = callback.data.split(":", 1)[1]
    selected = {"telegram"}
    await state.set_state(PublishingFlow.selecting_platforms)
    await state.update_data(video_project_id=video_project_id, publish_platforms=list(selected))
    await callback.message.answer(
        "Выберите площадки:",
        reply_markup=platform_selection_keyboard(video_project_id, selected),
    )


@router.callback_query(F.data.startswith("pubtoggle:"))
async def toggle_publish_platform(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.data or not isinstance(callback.message, Message):
        return
    _, platform, video_project_id = callback.data.split(":", 2)
    data = await state.get_data()
    selected = set(data.get("publish_platforms", []))
    if platform in selected:
        selected.remove(platform)
    else:
        selected.add(platform)
    await state.update_data(video_project_id=video_project_id, publish_platforms=list(selected))
    await callback.message.edit_reply_markup(
        reply_markup=platform_selection_keyboard(video_project_id, selected)
    )


@router.callback_query(F.data.startswith("pubprepare:"))
async def prepare_publication_preview(
    callback: CallbackQuery, state: FSMContext, backend: BackendClient
) -> None:
    await callback.answer()
    if not callback.data or not isinstance(callback.message, Message):
        return
    data = await state.get_data()
    platforms = list(data.get("publish_platforms", []))
    if not platforms:
        await callback.message.answer("Выберите хотя бы одну площадку.")
        return
    video_project_id = callback.data.split(":", 1)[1]
    await callback.message.answer("Готовлю отдельные тексты для площадок…")
    package = await backend.prepare_publish_package(video_project_id, platforms)
    for variant in package["variants"]:
        if variant["platform"] == "tiktok" and variant["settings"].get("requires_rerender"):
            media = await backend.prepare_platform_variant_media(variant["id"])
            if media["queued"]:
                await callback.message.answer(
                    "TikTok-safe версия рендерится без watermark/logo; AI-анализ не повторяется."
                )
    await state.update_data(
        publish_package_id=package["package"]["id"],
        publish_variants=package["variants"],
        video_project_id=video_project_id,
    )
    await callback.message.answer(
        format_publication_preview(package["variants"]),
        reply_markup=publication_preview_keyboard(package["package"]["id"], package["variants"]),
    )


@router.callback_query(F.data.startswith("pubedit:"))
async def request_variant_edit(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.data or not isinstance(callback.message, Message):
        return
    variant_id = callback.data.split(":", 1)[1]
    variants = (await state.get_data()).get("publish_variants", [])
    variant = next((item for item in variants if item["id"] == variant_id), None)
    if variant is None:
        await callback.message.answer("Preview устарел. Откройте публикацию заново.")
        return
    await state.set_state(PublishingFlow.editing_variant)
    await state.update_data(edit_variant_id=variant_id, edit_platform=variant["platform"])
    await callback.message.answer(
        "Первая строка — заголовок. После пустой строки — caption/description."
    )


@router.message(PublishingFlow.editing_variant, F.text)
async def apply_variant_edit(message: Message, state: FSMContext, backend: BackendClient) -> None:
    data = await state.get_data()
    variant_id = data.get("edit_variant_id")
    platform = data.get("edit_platform")
    if not variant_id or not platform:
        await state.clear()
        return
    title, separator, body = (message.text or "").partition("\n\n")
    fields: dict[str, str] = {"title": title.strip()}
    fields["description" if platform == "youtube" else "caption"] = (
        body.strip() if separator else title.strip()
    )
    await backend.update_platform_variant(str(variant_id), **fields)
    package_id = str(data["publish_package_id"])
    package = await backend.get_publish_package(package_id)
    await state.set_state(PublishingFlow.selecting_platforms)
    await state.update_data(publish_variants=package["variants"])
    await message.answer(
        format_publication_preview(package["variants"]),
        reply_markup=publication_preview_keyboard(package_id, package["variants"]),
    )


@router.callback_query(F.data.startswith("pubregen:"))
async def regenerate_publication_texts(
    callback: CallbackQuery, state: FSMContext, backend: BackendClient
) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message):
        return
    data = await state.get_data()
    video_project_id = str(data.get("video_project_id", ""))
    platforms = list(data.get("publish_platforms", []))
    package = await backend.prepare_publish_package(video_project_id, platforms, regenerate=True)
    await state.update_data(publish_variants=package["variants"])
    await callback.message.answer(
        format_publication_preview(package["variants"]),
        reply_markup=publication_preview_keyboard(package["package"]["id"], package["variants"]),
    )


@router.callback_query(F.data.startswith("pubtiktok:"))
async def configure_tiktok_variant(
    callback: CallbackQuery, state: FSMContext, backend: BackendClient
) -> None:
    await callback.answer()
    if not callback.data or not isinstance(callback.message, Message):
        return
    variant_id = callback.data.split(":", 1)[1]
    data = await state.get_data()
    package = await backend.get_publish_package(str(data["publish_package_id"]))
    variant = next(item for item in package["variants"] if item["id"] == variant_id)
    accounts = await backend.list_platform_accounts(package["package"]["project_id"], "tiktok")
    account = next((item for item in accounts if item["is_active"]), None)
    if account is None:
        await callback.message.answer("Сначала подключите активный TikTok account.")
        return
    report = await backend.validate_platform_variant(variant_id, account["id"])
    capabilities = report.get("capabilities", {})
    if not capabilities:
        await callback.message.answer("Не удалось получить TikTok creator capabilities.")
        return
    await state.update_data(
        tiktok_variant_id=variant_id,
        tiktok_settings=variant["settings"],
        tiktok_capabilities=capabilities,
    )
    await callback.message.answer(
        "TikTok требует явного выбора visibility и разрешений:",
        reply_markup=tiktok_settings_keyboard(variant_id, variant["settings"], capabilities),
    )


async def _save_tiktok_settings(
    message: Message, state: FSMContext, backend: BackendClient
) -> None:
    data = await state.get_data()
    variant_id = str(data["tiktok_variant_id"])
    settings = dict(data["tiktok_settings"])
    capabilities = dict(data["tiktok_capabilities"])
    await backend.update_platform_variant(variant_id, settings=settings)
    await message.edit_reply_markup(
        reply_markup=tiktok_settings_keyboard(variant_id, settings, capabilities)
    )


@router.callback_query(F.data.startswith("ttps:"))
async def set_tiktok_privacy(
    callback: CallbackQuery, state: FSMContext, backend: BackendClient
) -> None:
    await callback.answer()
    if not callback.data or not isinstance(callback.message, Message):
        return
    _, code, _ = callback.data.split(":", 2)
    mapping = {
        "p": "PUBLIC_TO_EVERYONE",
        "f": "MUTUAL_FOLLOW_FRIENDS",
        "s": "SELF_ONLY",
    }
    data = await state.get_data()
    settings = dict(data["tiktok_settings"])
    settings["privacy_level"] = mapping[code]
    settings["user_consent_confirmed"] = False
    await state.update_data(tiktok_settings=settings)
    await _save_tiktok_settings(callback.message, state, backend)


@router.callback_query(F.data.startswith("ttop:"))
async def toggle_tiktok_option(
    callback: CallbackQuery, state: FSMContext, backend: BackendClient
) -> None:
    await callback.answer()
    if not callback.data or not isinstance(callback.message, Message):
        return
    _, code, _ = callback.data.split(":", 2)
    fields = {"c": "disable_comment", "d": "disable_duet", "s": "disable_stitch"}
    data = await state.get_data()
    settings = dict(data["tiktok_settings"])
    field = fields[code]
    settings[field] = not bool(settings.get(field, False))
    settings["user_consent_confirmed"] = False
    await state.update_data(tiktok_settings=settings)
    await _save_tiktok_settings(callback.message, state, backend)


@router.callback_query(F.data.startswith("ttok:"))
async def confirm_tiktok_options(
    callback: CallbackQuery, state: FSMContext, backend: BackendClient
) -> None:
    await callback.answer("Настройки подтверждены")
    if not isinstance(callback.message, Message):
        return
    data = await state.get_data()
    settings = dict(data["tiktok_settings"])
    settings["user_consent_confirmed"] = True
    await state.update_data(tiktok_settings=settings)
    await _save_tiktok_settings(callback.message, state, backend)


@router.callback_query(F.data.startswith("pubready:"))
async def choose_publication_time(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.data and isinstance(callback.message, Message):
        package_id = callback.data.split(":", 1)[1]
        await state.update_data(publish_package_id=package_id)
        await callback.message.answer(
            "Когда опубликовать? Время будет показано в timezone проекта.",
            reply_markup=publication_time_keyboard(package_id),
        )


@router.callback_query(F.data.startswith("pubday:"))
async def choose_publication_day(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not callback.data or not isinstance(callback.message, Message):
        return
    _, offset, package_id = callback.data.split(":", 2)
    await state.set_state(PublishingFlow.waiting_for_time)
    await state.update_data(publish_package_id=package_id, publish_day_offset=int(offset))
    await callback.message.answer("Введите время в формате ЧЧ:ММ, например 12:00.")


@router.callback_query(F.data.startswith("pubdate:"))
async def choose_publication_datetime(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.data and isinstance(callback.message, Message):
        await state.set_state(PublishingFlow.waiting_for_datetime)
        await state.update_data(publish_package_id=callback.data.split(":", 1)[1])
        await callback.message.answer("Введите дату и время: ДД.ММ.ГГГГ ЧЧ:ММ")


async def _package_timezone(package: dict[str, Any], backend: BackendClient) -> ZoneInfo:
    projects = await backend.list_projects()
    project = next(item for item in projects if item["id"] == package["package"]["project_id"])
    return ZoneInfo(project.get("timezone") or "UTC")


async def _submit_package(
    message: Message,
    package_id: str,
    backend: BackendClient,
    *,
    scheduled_at: datetime | None,
) -> None:
    package = await backend.get_publish_package(package_id)
    accounts = await backend.list_platform_accounts(package["package"]["project_id"])
    items = []
    missing = []
    for variant in package["variants"]:
        account = next(
            (
                item
                for item in accounts
                if item["platform"] == variant["platform"] and item["is_active"]
            ),
            None,
        )
        if account is None:
            missing.append(variant["platform"])
            continue
        moment = scheduled_at.isoformat() if scheduled_at else "now"
        items.append(
            {
                "platform_variant_id": variant["id"],
                "platform_account_id": account["id"],
                "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
                "publish_now": scheduled_at is None,
                "idempotency_key": f"bot:{package_id}:{variant['platform']}:{moment}",
                "metadata": {"notify_chat_id": message.chat.id},
            }
        )
    if missing:
        await message.answer("Нет активного аккаунта: " + ", ".join(missing))
    if not items:
        return
    result = await backend.create_publications(items)
    failed = [report for report in result["validation"] if not report["ready"]]
    if scheduled_at and result["publications"]:
        await message.answer(
            f"📅 Контент запланирован: {scheduled_at.astimezone().strftime('%d.%m %H:%M')}."
        )
    elif result["publications"]:
        await message.answer("🚀 Публикация поставлена в очередь.")
    if failed:
        lines = ["⚠️ Некоторые площадки не готовы:"]
        for report in failed:
            issues = "; ".join(issue["message"] for issue in report["issues"])
            lines.append(f"{report['platform']}: {issues}")
        await message.answer("\n".join(lines))


@router.callback_query(F.data.startswith("pubnow:"))
async def submit_publication_now(
    callback: CallbackQuery, state: FSMContext, backend: BackendClient
) -> None:
    await callback.answer()
    if callback.data and isinstance(callback.message, Message):
        await _submit_package(
            callback.message, callback.data.split(":", 1)[1], backend, scheduled_at=None
        )
        await state.clear()


@router.message(PublishingFlow.waiting_for_time, F.text)
async def submit_publication_time(
    message: Message, state: FSMContext, backend: BackendClient
) -> None:
    data = await state.get_data()
    try:
        hour, minute = (int(item) for item in (message.text or "").split(":"))
        package = await backend.get_publish_package(str(data["publish_package_id"]))
        timezone = await _package_timezone(package, backend)
        local = datetime.now(timezone) + timedelta(days=int(data["publish_day_offset"]))
        scheduled = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if scheduled <= datetime.now(timezone):
            raise ValueError
    except (ValueError, KeyError):
        await message.answer("Нужно будущее время в формате ЧЧ:ММ.")
        return
    await _submit_package(message, str(data["publish_package_id"]), backend, scheduled_at=scheduled)
    await state.clear()


@router.message(PublishingFlow.waiting_for_datetime, F.text)
async def submit_publication_datetime(
    message: Message, state: FSMContext, backend: BackendClient
) -> None:
    data = await state.get_data()
    try:
        package = await backend.get_publish_package(str(data["publish_package_id"]))
        timezone = await _package_timezone(package, backend)
        scheduled = datetime.strptime(message.text or "", "%d.%m.%Y %H:%M").replace(tzinfo=timezone)
        if scheduled <= datetime.now(timezone):
            raise ValueError
    except (ValueError, KeyError):
        await message.answer("Нужна будущая дата: ДД.ММ.ГГГГ ЧЧ:ММ")
        return
    await _submit_package(message, str(data["publish_package_id"]), backend, scheduled_at=scheduled)
    await state.clear()


@router.message(Command("publications"))
@router.message(F.text == "📅 Публикации")
async def show_publications(message: Message, backend: BackendClient) -> None:
    items = await backend.list_publications()
    await message.answer(
        format_publications(items), reply_markup=publications_filter_keyboard(items)
    )


@router.callback_query(F.data.startswith("publist:"))
async def filter_publications(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if not callback.data or not isinstance(callback.message, Message):
        return
    requested = callback.data.split(":", 1)[1]
    status_groups = {
        "publishing": ["queued", "publishing", "processing", "retry_wait"],
        "published": ["published", "published_with_warning"],
        "failed": ["failed"],
        "scheduled": ["scheduled"],
    }
    items = []
    for status in status_groups.get(requested, [requested]):
        items.extend(await backend.list_publications(status))
    items.sort(key=lambda item: item["created_at"], reverse=True)
    await callback.message.edit_text(
        format_publications(items), reply_markup=publications_filter_keyboard(items)
    )


@router.callback_query(F.data.startswith("pubopen:"))
async def open_publication(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if callback.data and isinstance(callback.message, Message):
        publication = await backend.get_publication(callback.data.split(":", 1)[1])
        await callback.message.answer(
            format_publications([publication]),
            reply_markup=publication_detail_keyboard(publication),
        )


async def _publication_timezone(publication: dict[str, Any], backend: BackendClient) -> ZoneInfo:
    package = await backend.get_publish_package(publication["publish_package_id"])
    return await _package_timezone(package, backend)


@router.callback_query(F.data.startswith("pubresched:"))
async def request_publication_reschedule(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.data and isinstance(callback.message, Message):
        await state.set_state(PublishingFlow.waiting_for_reschedule)
        await state.update_data(publication_id=callback.data.split(":", 1)[1])
        await callback.message.answer("Введите новые дату и время: ДД.ММ.ГГГГ ЧЧ:ММ")


@router.message(PublishingFlow.waiting_for_reschedule, F.text)
async def reschedule_publication(
    message: Message, state: FSMContext, backend: BackendClient
) -> None:
    data = await state.get_data()
    try:
        publication = await backend.get_publication(str(data["publication_id"]))
        timezone = await _publication_timezone(publication, backend)
        scheduled = datetime.strptime(message.text or "", "%d.%m.%Y %H:%M").replace(tzinfo=timezone)
        if scheduled <= datetime.now(timezone):
            raise ValueError
    except (ValueError, KeyError):
        await message.answer("Нужна будущая дата: ДД.ММ.ГГГГ ЧЧ:ММ")
        return
    result = await backend.reschedule_publication(str(data["publication_id"]), scheduled)
    await message.answer("⏰ Время обновлено.\n" + format_publications([result]))
    await state.clear()


@router.callback_query(F.data.startswith("pubcontent:"))
async def request_publication_content(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if callback.data and isinstance(callback.message, Message):
        await state.set_state(PublishingFlow.editing_publication)
        await state.update_data(publication_id=callback.data.split(":", 1)[1])
        await callback.message.answer(
            "Отправьте заголовок первой строкой, затем пустую строку и новый текст."
        )


@router.message(PublishingFlow.editing_publication, F.text)
async def edit_publication_content(
    message: Message, state: FSMContext, backend: BackendClient
) -> None:
    data = await state.get_data()
    parts = (message.text or "").split("\n\n", 1)
    if len(parts) != 2 or not all(part.strip() for part in parts):
        await message.answer("Нужны заголовок, пустая строка и текст.")
        return
    publication = await backend.get_publication(str(data["publication_id"]))
    body_field = "description" if publication["platform"] == "youtube" else "caption"
    result = await backend.update_publication_content(
        str(data["publication_id"]), title=parts[0].strip(), **{body_field: parts[1].strip()}
    )
    await message.answer("✅ Текст обновлён и повторно проверен.\n" + format_publications([result]))
    await state.clear()


@router.callback_query(F.data.startswith("pubrun:"))
async def run_publication(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if callback.data and isinstance(callback.message, Message):
        result = await backend.publish_now(callback.data.split(":", 1)[1])
        await callback.message.answer(format_publications([result]))


@router.callback_query(F.data.startswith("pubcancel:"))
async def cancel_scheduled_publication(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer("Отменено")
    if callback.data and isinstance(callback.message, Message):
        result = await backend.cancel_publication(callback.data.split(":", 1)[1])
        await callback.message.answer(format_publications([result]))


@router.callback_query(F.data.startswith("pubretry:"))
async def retry_failed_publication(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if callback.data and isinstance(callback.message, Message):
        result = await backend.retry_publication(callback.data.split(":", 1)[1])
        await callback.message.answer(format_publications([result]))


@router.callback_query(F.data.startswith("video_archive:"))
async def archive_video(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer("Архивировано")
    if callback.data:
        await backend.archive_video(callback.data.split(":", 1)[1])
    if isinstance(callback.message, Message):
        if callback.message.video:
            await callback.message.edit_caption(caption="VideoProject перемещён в архив.")
        else:
            await callback.message.edit_text("VideoProject перемещён в архив.")


@router.callback_query(F.data.startswith("video_edit:"))
async def video_edit_menu(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or not callback.data:
        return
    project = await backend.get_video_project(callback.data.split(":", 1)[1])
    await callback.message.answer(
        format_video_edit(project), reply_markup=video_edit_keyboard(project["id"])
    )


@router.callback_query(F.data.startswith("video_faster:"))
@router.callback_query(F.data.startswith("video_calmer:"))
async def adjust_video_pace(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or not callback.data:
        return
    action, project_id = callback.data.split(":", 1)
    current = await backend.get_video_project(project_id)
    instruction = (
        "Сделай монтаж быстрее, но не режь слова и естественные микропаузы."
        if action == "video_faster"
        else "Сделай монтаж спокойнее и сохрани больше естественных пауз."
    )
    project = await backend.generate_video_edit_plan(
        project_id, int(current.get("selected_concept") or 0), instruction
    )
    await callback.message.answer(
        format_video_plan(project), reply_markup=video_plan_keyboard(project_id)
    )


@router.callback_query(F.data.startswith("video_style:"))
async def video_style_menu(callback: CallbackQuery) -> None:
    await callback.answer()
    if isinstance(callback.message, Message) and callback.data:
        project_id = callback.data.split(":", 1)[1]
        await callback.message.answer(
            "Выберите стиль субтитров:", reply_markup=video_style_keyboard(project_id)
        )


@router.callback_query(F.data.startswith("video_style_set:"))
async def set_video_style(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or not callback.data:
        return
    _, project_id, preset = callback.data.split(":", maxsplit=2)
    await backend.set_video_style(project_id, preset)
    await callback.message.answer(f"Стиль {preset.upper()} выбран. Пересобираю тот же план…")


@router.callback_query(F.data.startswith("video_simple:"))
async def simplify_video_render(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or not callback.data:
        return
    project_id = callback.data.split(":", 1)[1]
    await backend.set_video_style(project_id, "clean")
    await callback.message.answer("Запустил упрощённый рендер со стилем CLEAN.")


@router.callback_query(F.data.startswith("video_text:"))
async def show_video_text(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or not callback.data:
        return
    await _show_transcript_page(callback.message, callback.data.split(":", 1)[1], 0, backend)


@router.callback_query(F.data.startswith("video_text_page:"))
async def paginate_video_text(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or not callback.data:
        return
    _, project_id, raw_page = callback.data.split(":", maxsplit=2)
    await _show_transcript_page(callback.message, project_id, int(raw_page), backend)


@router.callback_query(F.data.startswith("video_text_replace:"))
async def request_subtitle_replacement(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or not callback.data:
        return
    await state.set_state(VideoEditFlow.waiting_for_subtitle_replacement)
    await state.update_data(video_project_id=callback.data.split(":", 1)[1])
    await callback.message.answer("Отправьте замену в формате: рест апи => REST API")


@router.message(VideoEditFlow.waiting_for_subtitle_replacement, F.text)
async def apply_subtitle_replacement(
    message: Message, state: FSMContext, backend: BackendClient
) -> None:
    project_id = (await state.get_data()).get("video_project_id")
    old, separator, new = (message.text or "").partition("=>")
    if not project_id or not separator or not old.strip() or not new.strip():
        await message.answer("Нужен формат: исходная фраза => исправленная фраза")
        return
    await backend.update_transcript(str(project_id), old.strip(), new.strip())
    await state.clear()
    await message.answer("Замена сохранена без изменения timestamps. Нажмите «Пересобрать».")


@router.callback_query(F.data.startswith("video_manual:"))
async def request_manual_clip(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or not callback.data:
        return
    await state.set_state(VideoEditFlow.waiting_for_manual_range)
    await state.update_data(video_source_id=callback.data.split(":", 1)[1])
    await callback.message.answer("Отправьте диапазон, например: 00:45 - 01:23")


@router.message(VideoEditFlow.waiting_for_manual_range, F.text)
async def create_manual_clip(message: Message, state: FSMContext, backend: BackendClient) -> None:
    source_id = (await state.get_data()).get("video_source_id")
    try:
        raw_start, raw_end = (message.text or "").split("-", maxsplit=1)
        start = _timestamp_seconds(raw_start.strip())
        end = _timestamp_seconds(raw_end.strip())
        if end <= start:
            raise ValueError
    except ValueError:
        await message.answer("Не понял диапазон. Используйте формат 00:45 - 01:23.")
        return
    project = await backend.create_manual_video_project(str(source_id), start, end)
    await state.clear()
    await message.answer(
        format_video_plan(project), reply_markup=video_plan_keyboard(project["id"])
    )


def _timestamp_seconds(value: str) -> float:
    parts = [float(item) for item in value.split(":")]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    raise ValueError("Invalid timestamp")


async def _show_transcript_page(
    message: Message, project_id: str, page: int, backend: BackendClient
) -> None:
    project = await backend.get_video_project(project_id)
    source = await backend.get_source(project["source_item_id"])
    text = source.get("transcript") or "Транскрипция недоступна."
    page_size = 3200
    pages = max(1, (len(text) + page_size - 1) // page_size)
    safe_page = min(max(page, 0), pages - 1)
    chunk = text[safe_page * page_size : (safe_page + 1) * page_size]
    await message.answer(
        f"Текст {safe_page + 1}/{pages}\n\n{chunk}",
        reply_markup=video_text_keyboard(project_id, safe_page, pages),
    )


@router.callback_query(F.data.startswith("source_ideas:"))
async def source_ideas(callback: CallbackQuery, state: FSMContext, backend: BackendClient) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or not callback.data:
        return
    source_id = callback.data.split(":", 1)[1]
    ideas = await backend.generate_ideas(source_id)
    await state.update_data(source_id=source_id)
    await state.set_state(IdeaFlow.choosing_angle)
    await callback.message.answer(format_angles(ideas), reply_markup=angle_keyboard(ideas))


@router.callback_query(F.data.startswith("source_post:"))
async def source_post(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or not callback.data:
        return
    await callback.message.answer("Готовлю Telegram-пост…")
    try:
        draft = await backend.generate_source_post(callback.data.split(":", 1)[1])
    except httpx.TimeoutException:
        await callback.message.answer(
            "⚠️ Локальная AI-модель не ответила вовремя. Запрос остановлен — попробуйте ещё раз."
        )
        return
    except httpx.HTTPError:
        await callback.message.answer("⚠️ Не удалось сгенерировать пост. Попробуйте ещё раз.")
        return
    text = f"{draft['title']}\n\n{draft['script']}\n\n{draft['call_to_action']}"
    await callback.message.answer(text)


@router.callback_query(F.data.startswith("source_note:"))
async def request_source_note(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or not callback.data:
        return
    await state.set_state(SourceContextFlow.waiting_for_note)
    await state.update_data(note_source_id=callback.data.split(":", 1)[1])
    await callback.message.answer("Отправьте уточнение текстом.")


@router.callback_query(F.data.startswith("source_voice_note:"))
async def request_source_voice_note(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.answer()
    if not isinstance(callback.message, Message) or not callback.data:
        return
    await state.set_state(SourceContextFlow.waiting_for_voice_note)
    await state.update_data(note_source_id=callback.data.split(":", 1)[1])
    await callback.message.answer("Отправьте ответ голосовым сообщением.")


@router.message(SourceContextFlow.waiting_for_note, F.text)
async def add_source_note(message: Message, state: FSMContext, backend: BackendClient) -> None:
    assert message.from_user is not None
    source_id = (await state.get_data()).get("note_source_id")
    if not source_id:
        await state.clear()
        await message.answer("Сессия уточнения истекла.")
        return
    await backend.add_source_note(str(source_id), message.from_user.id, message.text or "")
    await state.clear()
    await message.answer("Уточнение добавлено. Материал анализируется заново.")


@router.message(SourceContextFlow.waiting_for_voice_note, F.voice)
async def add_source_voice_note(
    message: Message, event_update: Update, state: FSMContext, backend: BackendClient
) -> None:
    assert message.from_user is not None
    source_id = (await state.get_data()).get("note_source_id")
    if not source_id:
        await state.clear()
        await message.answer("Сессия уточнения истекла.")
        return
    payload = build_source_payload(message, event_update.update_id)
    await backend.add_source_voice_note(str(source_id), message.from_user.id, payload)
    await state.clear()
    await message.answer("Голосовое уточнение получено и обрабатывается.")


@router.callback_query(F.data.startswith("source_archive:"))
async def archive_source(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer("Архивировано")
    if callback.data:
        await backend.archive_source(callback.data.split(":", 1)[1])
    if isinstance(callback.message, Message):
        await callback.message.edit_text("Материал перемещён в архив.")


@router.callback_query(F.data.startswith("source_retry:"))
async def retry_source(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if callback.data:
        await backend.retry_source(callback.data.split(":", 1)[1])
    if isinstance(callback.message, Message):
        await callback.message.edit_text("Повторная обработка запущена.")


@router.callback_query(F.data.startswith("source_delete:"))
async def delete_source(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer()
    if callback.data:
        await backend.delete_source(callback.data.split(":", 1)[1])
    if isinstance(callback.message, Message):
        await callback.message.edit_text("Материал удалён.")


@router.callback_query(F.data.startswith("source_keep:"))
async def keep_source(callback: CallbackQuery) -> None:
    await callback.answer("Материал остаётся в Inbox")


@router.message(F.text.in_({"💡 Идеи", "📝 Черновики", "📅 Контент-план", "⚙️ Настройки"}))
async def future_section(message: Message) -> None:
    await message.answer("Раздел будет расширен позже. Сейчас используйте Inbox или «Новая идея».")


@router.message(
    StateFilter(None),
    F.content_type.in_({"text", "voice", "audio", "video", "video_note", "photo", "document"}),
)
async def automatic_inbox(message: Message, event_update: Update, backend: BackendClient) -> None:
    try:
        payload = build_source_payload(message, event_update.update_id)
        result = await backend.ingest(payload)
        if result["created"]:
            await message.answer(received_message(result["source"]["type"]))
        else:
            await message.answer("Этот материал уже есть в Inbox.")
    except httpx.HTTPStatusError as exc:
        if exc.response.status_code == 413:
            await message.answer("Файл слишком большой для загрузки.")
        else:
            await message.answer("Не удалось зарегистрировать материал. Попробуйте ещё раз.")
    except httpx.HTTPError:
        await message.answer("Backend временно недоступен. Попробуйте ещё раз.")
