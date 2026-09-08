from app.bot.formatters import format_publication_preview, format_publications
from app.bot.keyboards import (
    approved_video_keyboard,
    platform_selection_keyboard,
    publication_detail_keyboard,
    publication_preview_keyboard,
    publication_time_keyboard,
    publications_filter_keyboard,
    tiktok_settings_keyboard,
)
from app.main import app


def test_phase5_openapi_exposes_complete_publishing_workflow() -> None:
    schema = app.openapi()
    assert schema["info"]["version"] == "0.5.0"
    paths = schema["paths"]
    expected = {
        "/video-projects/{video_project_id}/publish-package": "post",
        "/publish-packages": "get",
        "/publish-packages/{package_id}": "get",
        "/platform-variants/{variant_id}": "patch",
        "/platform-variants/{variant_id}/prepare-media": "post",
        "/platform-variants/{variant_id}/validate": "post",
        "/platform-accounts": "post",
        "/publications/batch": "post",
        "/publications": "get",
        "/publications/{publication_id}/schedule": "post",
        "/publications/{publication_id}/publish-now": "post",
        "/publications/{publication_id}/cancel": "post",
        "/publications/{publication_id}/retry": "post",
        "/publications/{publication_id}/content": "patch",
        "/oauth/{platform}/start": "post",
        "/oauth/{platform}/callback": "get",
        "/webhooks/tiktok": "post",
    }
    for path, method in expected.items():
        assert method in paths[path]


def test_publication_bot_selection_preview_schedule_and_history_controls() -> None:
    video_id = "00000000-0000-0000-0000-000000000001"
    package_id = "00000000-0000-0000-0000-000000000002"
    variant_id = "00000000-0000-0000-0000-000000000003"
    assert (
        approved_video_keyboard(video_id)
        .inline_keyboard[0][0]
        .callback_data.startswith("video_publish:")
    )
    selection = platform_selection_keyboard(video_id, {"telegram", "youtube"})
    assert selection.inline_keyboard[0][0].text.startswith("✅")
    assert selection.inline_keyboard[2][0].text.startswith("⬜")
    variants = [
        {
            "id": variant_id,
            "platform": "tiktok",
            "title": "TikTok title",
            "caption": "TikTok caption",
            "description": "",
            "hashtags": ["код"],
            "settings": {"privacy_level": "SELF_ONLY"},
        }
    ]
    preview = publication_preview_keyboard(package_id, variants)
    callbacks = [button.callback_data for row in preview.inline_keyboard for button in row]
    assert any(item.startswith("pubedit:") for item in callbacks)
    assert any(item.startswith("pubtiktok:") for item in callbacks)
    assert "Visibility: SELF_ONLY" in format_publication_preview(variants)
    times = publication_time_keyboard(package_id)
    assert times.inline_keyboard[0][0].callback_data.startswith("pubnow:")
    assert times.inline_keyboard[1][1].text == "Завтра"


def test_tiktok_capability_keyboard_hides_unavailable_options() -> None:
    keyboard = tiktok_settings_keyboard(
        "00000000-0000-0000-0000-000000000003",
        {"privacy_level": "SELF_ONLY", "disable_comment": True},
        {
            "privacy_level_options": ["SELF_ONLY"],
            "comment_disabled": True,
            "duet_disabled": False,
            "stitch_disabled": True,
        },
    )
    labels = [button.text for row in keyboard.inline_keyboard for button in row]
    assert "✅ Only me" in labels
    assert not any("Комментарии" in item for item in labels)
    assert any("Duet" in item for item in labels)
    assert not any("Stitch" in item for item in labels)


def test_publication_history_formatter_and_retry_control() -> None:
    item = {
        "id": "00000000-0000-0000-0000-000000000004",
        "status": "failed",
        "platform": "youtube",
        "scheduled_at": None,
        "variant_snapshot": {"title": "REST API и двойной запрос"},
    }
    assert "❌ REST API" in format_publications([item])
    keyboard = publications_filter_keyboard([item])
    assert keyboard.inline_keyboard[-1][0].callback_data.startswith("pubopen:")

    scheduled = {**item, "status": "scheduled"}
    detail = publication_detail_keyboard(scheduled)
    callbacks = [button.callback_data for row in detail.inline_keyboard for button in row]
    assert any(value.startswith("pubcontent:") for value in callbacks)
    assert any(value.startswith("pubresched:") for value in callbacks)
    assert any(value.startswith("pubcancel:") for value in callbacks)
