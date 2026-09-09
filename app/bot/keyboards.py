import base64
import uuid

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)


def main_menu() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🎬 Новый ролик"), KeyboardButton(text="📂 Мои ролики")],
            [KeyboardButton(text="➕ Новая идея"), KeyboardButton(text="📥 Контент-инбокс")],
            [KeyboardButton(text="📎 Добавить материалы"), KeyboardButton(text="🗂 Материалы")],
            [KeyboardButton(text="💡 Идеи"), KeyboardButton(text="📝 Черновики")],
            [KeyboardButton(text="📅 Публикации"), KeyboardButton(text="⚙️ Настройки")],
        ],
        resize_keyboard=True,
    )


def production_keyboard(project: dict[str, object]) -> InlineKeyboardMarkup:
    project_id = str(project["id"])
    rows = [
        [
            InlineKeyboardButton(
                text="🧠 Развить идею", callback_data=f"prod_develop:{project_id}"
            ),
            InlineKeyboardButton(text="📝 Сценарий", callback_data=f"prod_script:{project_id}"),
        ],
        [
            InlineKeyboardButton(
                text="➕ Добавить материал", callback_data=f"prod_add:{project_id}"
            ),
            InlineKeyboardButton(text="📎 Материалы", callback_data=f"prod_materials:{project_id}"),
        ],
    ]
    if project.get("primary_voiceover_id"):
        rows.append(
            [
                InlineKeyboardButton(
                    text="🎬 Начать монтаж", callback_data=f"prod_assemble:{project_id}"
                )
            ]
        )
    if project.get("active_timeline_revision_id"):
        rows.extend(
            [
                [
                    InlineKeyboardButton(
                        text="👁 Preview", callback_data=f"prod_preview:{project_id}"
                    ),
                    InlineKeyboardButton(
                        text="✅ Финализировать", callback_data=f"prod_final:{project_id}"
                    ),
                ],
                [InlineKeyboardButton(text="📝 Правки", callback_data=f"prod_replan:{project_id}")],
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def production_list_keyboard(projects: list[dict[str, object]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"🎬 {str(project.get('working_title') or project.get('title'))[:45]}",
                    callback_data=f"prod_open:{project['id']}",
                )
            ]
            for project in projects[:20]
        ]
    )


def develop_idea_keyboard(production_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💡 Добавить мысли",
                    callback_data=f"prod_develop_add:{production_id}:thoughts",
                ),
                InlineKeyboardButton(
                    text="📚 Добавить факты",
                    callback_data=f"prod_develop_add:{production_id}:facts",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🎯 Найти сильный hook", callback_data=f"prod_hook:{production_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🧩 Что ещё рассказать",
                    callback_data=f"prod_develop_add:{production_id}:gaps",
                ),
                InlineKeyboardButton(
                    text="📝 Расширить материал",
                    callback_data=f"prod_develop_add:{production_id}:expand",
                ),
            ],
        ]
    )


def script_version_keyboard(production_id: str, script_id: str) -> InlineKeyboardMarkup:
    token = base64.urlsafe_b64encode(
        uuid.UUID(production_id).bytes + uuid.UUID(script_id).bytes
    ).decode().rstrip("=")
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Утвердить", callback_data=f"prod_approve:{token}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Изменить", callback_data=f"prod_script_edit:{production_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="➕ Дополнить", callback_data=f"prod_script_edit:{production_id}"
                ),
                InlineKeyboardButton(
                    text="🔥 Сильнее начало", callback_data=f"prod_hook:{production_id}"
                ),
            ],
        ]
    )


def setup_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🤖 AI", callback_data="setup:ai")],
            [InlineKeyboardButton(text="🎙 Speech-to-Text", callback_data="setup:stt")],
            [InlineKeyboardButton(text="🎨 Бренд", callback_data="setup:brand")],
            [InlineKeyboardButton(text="⚙️ Render", callback_data="setup:render")],
            [InlineKeyboardButton(text="🔐 Security", callback_data="setup:security")],
            [InlineKeyboardButton(text="📊 Диагностика", callback_data="setup:diagnostics")],
        ]
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


def tiktok_settings_keyboard(
    variant_id: str, settings: dict[str, object], capabilities: dict[str, object]
) -> InlineKeyboardMarkup:
    privacy_labels = {
        "PUBLIC_TO_EVERYONE": "Public",
        "MUTUAL_FOLLOW_FRIENDS": "Friends",
        "SELF_ONLY": "Only me",
    }
    privacy_codes = {
        "PUBLIC_TO_EVERYONE": "p",
        "MUTUAL_FOLLOW_FRIENDS": "f",
        "SELF_ONLY": "s",
    }
    privacy_options_value = capabilities.get("privacy_level_options", [])
    privacy_options = (
        [str(value) for value in privacy_options_value]
        if isinstance(privacy_options_value, list)
        else []
    )
    rows = [
        [
            InlineKeyboardButton(
                text=("✅ " if settings.get("privacy_level") == value else "⬜ ")
                + privacy_labels.get(value, value),
                callback_data=f"ttps:{privacy_codes[value]}:{variant_id}",
            )
        ]
        for value in privacy_options
        if value in privacy_codes
    ]
    for code, setting, label, disabled_capability in (
        ("c", "disable_comment", "Комментарии", "comment_disabled"),
        ("d", "disable_duet", "Duet", "duet_disabled"),
        ("s", "disable_stitch", "Stitch", "stitch_disabled"),
    ):
        if not capabilities.get(disabled_capability):
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"{label}: {'Off' if settings.get(setting) else 'On'}",
                        callback_data=f"ttop:{code}:{variant_id}",
                    )
                ]
            )
    rows.append(
        [InlineKeyboardButton(text="✅ Подтвердить настройки", callback_data=f"ttok:{variant_id}")]
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


def approved_video_keyboard(video_project_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📤 Опубликовать", callback_data=f"video_publish:{video_project_id}"
                )
            ]
        ]
    )


def platform_selection_keyboard(video_project_id: str, selected: set[str]) -> InlineKeyboardMarkup:
    labels = {"telegram": "Telegram", "youtube": "YouTube", "tiktok": "TikTok"}
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{'✅' if platform in selected else '⬜'} {label}",
                    callback_data=f"pubtoggle:{platform}:{video_project_id}",
                )
            ]
            for platform, label in labels.items()
        ]
        + [
            [
                InlineKeyboardButton(
                    text="Продолжить →", callback_data=f"pubprepare:{video_project_id}"
                )
            ]
        ]
    )


def publication_preview_keyboard(
    package_id: str, variants: list[dict[str, object]]
) -> InlineKeyboardMarkup:
    labels = {"telegram": "Telegram", "youtube": "YouTube", "tiktok": "TikTok"}
    rows = [
        [
            InlineKeyboardButton(
                text=f"✏️ {labels.get(str(item['platform']), item['platform'])}",
                callback_data=f"pubedit:{item['id']}",
            )
        ]
        for item in variants
    ]
    for item in variants:
        if item["platform"] == "tiktok":
            rows.append(
                [
                    InlineKeyboardButton(
                        text="⚙️ TikTok visibility",
                        callback_data=f"pubtiktok:{item['id']}",
                    )
                ]
            )
    rows.extend(
        [
            [InlineKeyboardButton(text="✅ Всё хорошо", callback_data=f"pubready:{package_id}")],
            [
                InlineKeyboardButton(
                    text="🔄 Перегенерировать тексты", callback_data=f"pubregen:{package_id}"
                )
            ],
        ]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def publication_time_keyboard(package_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚀 Сейчас", callback_data=f"pubnow:{package_id}")],
            [
                InlineKeyboardButton(text="Сегодня", callback_data=f"pubday:0:{package_id}"),
                InlineKeyboardButton(text="Завтра", callback_data=f"pubday:1:{package_id}"),
            ],
            [InlineKeyboardButton(text="📅 Выбрать дату", callback_data=f"pubdate:{package_id}")],
        ]
    )


def publication_detail_keyboard(publication: dict[str, object]) -> InlineKeyboardMarkup:
    publication_id = str(publication["id"])
    status = str(publication["status"])
    rows: list[list[InlineKeyboardButton]] = []
    if status in {"draft", "scheduled", "queued", "retry_wait"}:
        rows.append(
            [InlineKeyboardButton(text="✏️ Тексты", callback_data=f"pubcontent:{publication_id}")]
        )
    if status in {"draft", "scheduled", "retry_wait"}:
        rows.append(
            [
                InlineKeyboardButton(
                    text="⏰ Изменить время", callback_data=f"pubresched:{publication_id}"
                )
            ]
        )
    if status in {"draft", "scheduled", "queued", "retry_wait"}:
        rows.append(
            [
                InlineKeyboardButton(
                    text="🚀 Опубликовать сейчас", callback_data=f"pubrun:{publication_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отменить", callback_data=f"pubcancel:{publication_id}"
                ),
            ]
        )
    if status == "failed":
        rows.append(
            [InlineKeyboardButton(text="🔄 Повторить", callback_data=f"pubretry:{publication_id}")]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def publications_filter_keyboard(items: list[dict[str, object]]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(text="⏳ Запланированные", callback_data="publist:scheduled"),
            InlineKeyboardButton(text="🚀 Публикуются", callback_data="publist:publishing"),
        ],
        [
            InlineKeyboardButton(text="✅ Опубликованные", callback_data="publist:published"),
            InlineKeyboardButton(text="❌ Ошибки", callback_data="publist:failed"),
        ],
    ]
    rows.extend(
        [InlineKeyboardButton(text=f"Открыть {index}", callback_data=f"pubopen:{item['id']}")]
        for index, item in enumerate(items[:10], start=1)
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


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
