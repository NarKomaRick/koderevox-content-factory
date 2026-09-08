import httpx
import structlog
from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.filters.state import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, Update

from app.bot.api_client import BackendClient
from app.bot.formatters import (
    format_angles,
    format_digest,
    format_draft,
    format_inbox,
    format_repurposed,
    format_source_detail,
    format_video_concepts,
    format_video_edit,
    format_video_plan,
)
from app.bot.ingestion import build_source_payload, received_message
from app.bot.keyboards import (
    angle_keyboard,
    draft_keyboard,
    inbox_keyboard,
    main_menu,
    source_detail_keyboard,
    video_concepts_keyboard,
    video_edit_keyboard,
    video_plan_keyboard,
    video_style_keyboard,
    video_text_keyboard,
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


@router.callback_query(F.data.startswith("video_approve:"))
async def approve_video(callback: CallbackQuery, backend: BackendClient) -> None:
    await callback.answer("Одобрено")
    if callback.data:
        await backend.approve_video(callback.data.split(":", 1)[1])
    if isinstance(callback.message, Message):
        await callback.message.answer("Видео одобрено ✅")


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
    draft = await backend.generate_source_post(callback.data.split(":", 1)[1])
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
