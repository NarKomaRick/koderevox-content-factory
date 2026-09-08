from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Новая идея"), KeyboardButton(text="📥 Контент-инбокс")],
            [KeyboardButton(text="📎 Добавить материалы"), KeyboardButton(text="🗂 Материалы")],
            [KeyboardButton(text="💡 Идеи"), KeyboardButton(text="📝 Черновики")],
            [KeyboardButton(text="📅 Контент-план"), KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True,
    )


def angle_keyboard(ideas: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=str(index), callback_data=f"idea:{idea['id']}")]
        for index, idea in enumerate(ideas, start=1)
    ]
    rows.extend(
        [
            [InlineKeyboardButton(text="🔄 Ещё варианты", callback_data="ideas:more")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="ideas:cancel")],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def draft_keyboard(draft_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Одобрить", callback_data=f"approve:{draft_id}"),
                InlineKeyboardButton(text="🔄 Перегенерировать", callback_data=f"regen:{draft_id}"),
            ],
            [
                InlineKeyboardButton(text="♻️ Адаптировать", callback_data=f"repurpose:{draft_id}"),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"delete:{draft_id}"),
            ],
        ]
    )


def inbox_keyboard(
    items: list[dict[str, object]], page: int, pages: int, filter_name: str = "new"
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="🔥 Лучшие", callback_data="inbox:best:1"),
            InlineKeyboardButton(text="🆕 Новые", callback_data="inbox:new:1"),
        ],
        [
            InlineKeyboardButton(text="🎤 Голос", callback_data="inbox:voice:1"),
            InlineKeyboardButton(text="🎥 Видео", callback_data="inbox:video:1"),
            InlineKeyboardButton(text="📝 Текст", callback_data="inbox:text:1"),
        ],
        [InlineKeyboardButton(text="🔗 Ссылки", callback_data="inbox:url:1")],
    ]
    rows.extend(
        [InlineKeyboardButton(text=f"Открыть {index}", callback_data=f"source_open:{item['id']}")]
        for index, item in enumerate(items, start=1)
    )
    navigation: list[InlineKeyboardButton] = []
    if page > 1:
        navigation.append(
            InlineKeyboardButton(text="←", callback_data=f"inbox:{filter_name}:{page - 1}")
        )
    if page < pages:
        navigation.append(
            InlineKeyboardButton(text="→", callback_data=f"inbox:{filter_name}:{page + 1}")
        )
    if navigation:
        rows.append(navigation)
    return InlineKeyboardMarkup(inline_keyboard=rows)


def source_detail_keyboard(source_id: str, *, video: bool = False) -> InlineKeyboardMarkup:
    manual_row = (
        [
            [
                InlineKeyboardButton(
                    text="✂️ Выбрать фрагмент", callback_data=f"video_manual:{source_id}"
                )
            ]
        ]
        if video
        else []
    )
    return InlineKeyboardMarkup(
        inline_keyboard=[
            *manual_row,
            [
                InlineKeyboardButton(text="🎬 Short", callback_data=f"source_short:{source_id}"),
                InlineKeyboardButton(text="💡 Идеи", callback_data=f"source_ideas:{source_id}"),
                InlineKeyboardButton(text="📝 TG-пост", callback_data=f"source_post:{source_id}"),
            ],
            [
                InlineKeyboardButton(text="➕ Дополнить", callback_data=f"source_note:{source_id}"),
                InlineKeyboardButton(text="📦 Архив", callback_data=f"source_archive:{source_id}"),
                InlineKeyboardButton(text="🗑 Удалить", callback_data=f"source_delete:{source_id}"),
            ],
        ]
    )


def video_concepts_keyboard(video_project_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=str(index + 1),
                    callback_data=f"video_concept:{video_project_id}:{index}",
                )
                for index in range(3)
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Другие варианты", callback_data=f"video_more:{video_project_id}"
                ),
                InlineKeyboardButton(
                    text="✏️ Свой запрос", callback_data=f"video_custom:{video_project_id}"
                ),
            ],
        ]
    )


def video_plan_keyboard(video_project_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="▶️ Собрать", callback_data=f"video_render:{video_project_id}"
                ),
                InlineKeyboardButton(
                    text="🎨 Визуалы", callback_data=f"video_visuals:{video_project_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✍️ Изменить план", callback_data=f"video_instruction:{video_project_id}"
                ),
                InlineKeyboardButton(
                    text="🗑 Удалить", callback_data=f"video_archive:{video_project_id}"
                ),
            ],
        ]
    )


def visual_suggestions_keyboard(video_project_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Применить все", callback_data=f"visual_apply:{video_project_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="➕ Добавить", callback_data=f"visual_manual:{video_project_id}"
                ),
                InlineKeyboardButton(
                    text="✏️ Настроить", callback_data=f"visual_instruction:{video_project_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🚫 Без вставок", callback_data=f"visual_none:{video_project_id}"
                ),
            ],
        ]
    )


def thumbnail_keyboard(
    items: list[dict[str, object]], video_project_id: str
) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text=str(index), callback_data=f"thumb_select:{item['id']}")
                for index, item in enumerate(items[:3], start=1)
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Свой текст", callback_data=f"thumb_custom:{video_project_id}"
                ),
                InlineKeyboardButton(
                    text="🔄 Другие", callback_data=f"thumb_more:{video_project_id}"
                ),
            ],
        ]
    )


def video_edit_keyboard(video_project_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="⚡ Сделать быстрее", callback_data=f"video_faster:{video_project_id}"
                ),
                InlineKeyboardButton(
                    text="🧘 Спокойнее", callback_data=f"video_calmer:{video_project_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="➕ Добавить момент", callback_data=f"video_add:{video_project_id}"
                ),
                InlineKeyboardButton(
                    text="➖ Убрать момент", callback_data=f"video_remove:{video_project_id}"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✍️ Написать инструкцию",
                    callback_data=f"video_instruction:{video_project_id}",
                )
            ],
        ]
    )


def video_style_keyboard(video_project_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=preset,
                    callback_data=f"video_style_set:{video_project_id}:{preset.lower()}",
                )
                for preset in ("CLEAN", "DYNAMIC", "TECH")
            ]
        ]
    )


def video_text_keyboard(video_project_id: str, page: int, pages: int) -> InlineKeyboardMarkup:
    navigation: list[InlineKeyboardButton] = []
    if page > 0:
        navigation.append(
            InlineKeyboardButton(
                text="←", callback_data=f"video_text_page:{video_project_id}:{page - 1}"
            )
        )
    if page + 1 < pages:
        navigation.append(
            InlineKeyboardButton(
                text="→", callback_data=f"video_text_page:{video_project_id}:{page + 1}"
            )
        )
    rows = [navigation] if navigation else []
    rows.append(
        [
            InlineKeyboardButton(
                text="Исправить фразу", callback_data=f"video_text_replace:{video_project_id}"
            )
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)
