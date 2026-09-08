from app.bot.formatters import format_video_concepts, format_video_plan
from app.bot.handlers import _timestamp_seconds
from app.bot.keyboards import video_concepts_keyboard, video_style_keyboard, video_text_keyboard


def test_video_concept_selection_keyboard_and_formatter() -> None:
    project = {
        "id": "video-1",
        "concepts": [
            {"title": f"Вариант {index}", "hook": "Hook", "focus": "Focus", "target_duration": 30}
            for index in range(1, 4)
        ],
    }
    text = format_video_concepts(project)
    keyboard = video_concepts_keyboard("video-1")
    assert "Нашёл 3 варианта" in text
    assert keyboard.inline_keyboard[0][1].callback_data == "video_concept:video-1:1"


def test_video_plan_style_and_transcript_pagination_controls() -> None:
    project = {
        "edit_plan": {
            "clips": [{"source_start": 2, "source_end": 12}],
            "hook_text": "Hook",
            "framing": "screen_fit",
            "pace": "calm",
        }
    }
    assert "10.0 сек" in format_video_plan(project)
    assert (
        video_style_keyboard("id").inline_keyboard[0][2].callback_data == "video_style_set:id:tech"
    )
    assert (
        video_text_keyboard("id", 1, 3).inline_keyboard[0][0].callback_data
        == "video_text_page:id:0"
    )


def test_manual_clip_timestamp_parser() -> None:
    assert _timestamp_seconds("45") == 45
    assert _timestamp_seconds("01:23") == 83
    assert _timestamp_seconds("1:02:03.5") == 3723.5
