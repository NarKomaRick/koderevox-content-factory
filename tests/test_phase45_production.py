import uuid

import httpx
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import select

from app.ai.mock import MockAIProvider
from app.core.config import Settings
from app.models import (
    EncryptedSecret,
    ProductionProject,
    Project,
    RuntimeSetting,
    ScriptVersion,
    SourceItem,
    TimelineRevision,
    User,
    VisualAsset,
)
from app.models.enums import (
    AssetStatus,
    AssetType,
    ProductionFactStatus,
    ProductionMaterialRole,
    ProductionStatus,
    ScriptSource,
    SourceStatus,
    SourceType,
    TimelineTrack,
    UserRole,
)
from app.schemas.production import (
    FactCreate,
    MaterialAttach,
    ProductionProjectCreate,
    ProductionTimeline,
    ScriptVersionCreate,
)
from app.services.errors import InvalidStateError
from app.services.production_projects import (
    ProductionContextBuilder,
    ProductionFactService,
    ProductionMaterialService,
    ProductionProjectService,
)
from app.services.production_scripts import ScriptVersionService
from app.services.production_timeline import (
    AutoAssemblyService,
    SemanticPlacementService,
    TimelineRevisionService,
    VisualGapAnalyzer,
    render_profile,
)
from app.services.runtime_settings import (
    AIConnectionTester,
    EncryptedDatabaseSecretStore,
    SettingsService,
)
from app.services.script_voice_aligner import ScriptVoiceAligner
from app.services.voiceovers import VoiceoverService


async def seed(session) -> tuple[Project, User, SourceItem]:
    project = (await session.scalars(select(Project))).first()
    assert project
    user = User(telegram_id=42, username="owner", role=UserRole.OWNER)
    session.add(user)
    await session.flush()
    source = SourceItem(
        project_id=project.id,
        user_id=user.id,
        type=SourceType.TEXT,
        original_text="Почему приложение не должно напрямую ходить в 1С",
        topic="Приложение и 1С",
        summary="Нужна стабильная backend-граница",
        content_analysis={"source_facts": ["1С бывает недоступна"]},
        processing_status=SourceStatus.READY,
    )
    session.add(source)
    await session.commit()
    return project, user, source


async def production(session) -> tuple[ProductionProject, User, Project]:
    project, user, source = await seed(session)
    item = await ProductionProjectService(session).create(
        ProductionProjectCreate(
            project_id=project.id,
            user_id=user.id,
            initial_source_item_id=source.id,
            title=source.original_text or "Ролик",
        )
    )
    return item, user, project


@pytest.mark.asyncio
async def test_production_project_crud_relationships_and_instructions(session) -> None:
    item, user, _ = await production(session)
    service = ProductionProjectService(session)
    updated = await service.update(
        item.id,
        working_title="Почему нужен backend",
        persistent_instructions=["без лица", "мемов мало"],
    )
    assert updated.user_id == user.id
    assert updated.persistent_instructions == ["без лица", "мемов мало"]
    with pytest.raises(InvalidStateError):
        await service.transition(item.id, ProductionStatus.READY_FOR_VOICEOVER)
    archived = await service.archive(item.id)
    assert archived.status == ProductionStatus.ARCHIVED


@pytest.mark.asyncio
async def test_script_versions_generate_edit_approve_history_diff_and_select(session) -> None:
    item, _, _ = await production(session)
    service = ScriptVersionService(session, MockAIProvider())
    v1 = await service.generate_v1(item.id)
    v2 = await service.edit(item.id, "Добавь пример с BestWay")
    v3 = await service.edit(item.id, "Начало скучное")
    assert [v1.version_number, v2.version_number, v3.version_number] == [1, 2, 3]
    assert "BestWay" in v2.content
    assert v2.diff["added"]
    await service.approve(v3.id)
    current = await ProductionProjectService(session).get(item.id)
    assert current.approved_script_version_id == v3.id
    assert current.status == ProductionStatus.READY_FOR_VOICEOVER
    await service.select(v1.id)
    assert (await service.history(item.id))[0].id == v1.id


@pytest.mark.asyncio
async def test_facts_and_context_keep_ai_proposals_separate(session) -> None:
    item, _, _ = await production(session)
    facts = ProductionFactService(session)
    proposed = await facts.add(item.id, FactCreate(text="AI думает, что 1С всегда медленная"))
    confirmed = await facts.add(
        item.id,
        FactCreate(text="В проекте был timeout 30 sec", status=ProductionFactStatus.VERIFIED),
    )
    with pytest.raises(InvalidStateError):
        await facts.set_status(proposed.id, ProductionFactStatus.USER_CONFIRMED)
    context = await ProductionContextBuilder(session).build(item.id)
    assert proposed.text in context["facts"]["proposed_not_factual"]
    assert confirmed.text in context["facts"]["confirmed"]


def test_alignment_near_exact_paraphrase_missing_and_extra() -> None:
    words_text = "приложение отправляло один запрос два раза потом всё окончательно сломалось"
    words = [
        {"word": word, "start": index * 0.5, "end": (index + 1) * 0.5}
        for index, word in enumerate(words_text.split())
    ]
    result = ScriptVoiceAligner().align(
        [
            {"id": "one", "text": "Приложение отправило запрос дважды"},
            {"id": "missing", "text": "Этой фразы вообще нет в речи"},
            {"id": "two", "text": "Всё окончательно сломалось"},
        ],
        words,
        words_text,
        duration=5.5,
    )
    assert result.sections[0].confidence > 0.45
    assert result.sections[0].start < result.sections[-1].start
    assert result.overall_confidence > 0
    assert result.unmatched_script
    degraded = ScriptVoiceAligner().align(
        [{"id": str(index), "text": f"section {index}"} for index in range(6)],
        [{"word": "okay", "start": 0, "end": 1}],
        "okay",
        duration=30,
    )
    assert len(degraded.sections) == 6
    assert degraded.sections[-1].end == 30


@pytest.mark.asyncio
async def test_voiceover_ingestion_replacement_and_timeline(session) -> None:
    item, user, project = await production(session)
    scripts = ScriptVersionService(session)
    script = await scripts.create(
        item.id,
        ScriptVersionCreate(
            content="Двойной запрос.\nВсё окончательно сломалось.",
            structured_sections=[
                {"id": "request", "text": "Приложение отправило двойной запрос"},
                {"id": "broken", "text": "Всё окончательно сломалось"},
            ],
            source=ScriptSource.USER,
        ),
    )
    await scripts.approve(script.id)
    words_text = "приложение отправило двойной запрос и всё окончательно сломалось"
    words = [
        {"word": word, "start": i * 0.5, "end": (i + 1) * 0.5}
        for i, word in enumerate(words_text.split())
    ]
    voice_source = SourceItem(
        project_id=project.id,
        user_id=user.id,
        type=SourceType.AUDIO,
        local_file_path="original/voice.mp3",
        processed_file_path="processed/voice.wav",
        duration_seconds=len(words) * 0.5,
        transcript=words_text,
        transcript_language="ru",
        transcript_segments=[
            {"start": 0, "end": len(words) * 0.5, "text": words_text, "words": words}
        ],
        processing_status=SourceStatus.READY,
    )
    session.add(voice_source)
    await session.commit()
    track = await VoiceoverService(session).create_from_processed_source(item.id, voice_source.id)
    assert track.words == words
    assert track.alignment_score and track.alignment_score > 0.5
    assert (await ProductionProjectService(session).get(item.id)).target_duration == track.duration
    replacement = SourceItem(
        project_id=project.id,
        user_id=user.id,
        type=SourceType.VOICE,
        local_file_path="original/new.ogg",
        processed_file_path="processed/new.wav",
        duration_seconds=track.duration,
        transcript=words_text,
        transcript_segments=voice_source.transcript_segments,
        processing_status=SourceStatus.READY,
    )
    session.add(replacement)
    await session.commit()
    new_track = await VoiceoverService(session).create_from_processed_source(
        item.id, replacement.id
    )
    await session.refresh(track)
    assert track.status.value == "replaced"
    assert new_track.id != track.id


@pytest.mark.asyncio
async def test_assets_auto_assembly_semantic_locked_incremental_and_rollback(session) -> None:
    item, user, project = await production(session)
    script = await ScriptVersionService(session).create(
        item.id,
        ScriptVersionCreate(
            content="Двойной запрос.\nВсё окончательно сломалось.",
            structured_sections=[
                {"id": "request", "text": "двойной запрос"},
                {"id": "broken", "text": "всё окончательно сломалось"},
            ],
        ),
    )
    await ScriptVersionService(session).approve(script.id)
    text = "приложение отправило двойной запрос потом всё окончательно сломалось"
    words = [{"word": word, "start": i, "end": i + 1.0} for i, word in enumerate(text.split())]
    source = SourceItem(
        project_id=project.id,
        user_id=user.id,
        type=SourceType.AUDIO,
        local_file_path="voice.ogg",
        processed_file_path="voice.wav",
        duration_seconds=float(len(words)),
        transcript=text,
        transcript_segments=[{"start": 0, "end": len(words), "text": text, "words": words}],
        processing_status=SourceStatus.READY,
    )
    screenshot = VisualAsset(
        project_id=project.id,
        type=AssetType.SCREENSHOT,
        status=AssetStatus.READY,
        original_path="screenshot.png",
        filename="login_screen.png",
        mime_type="image/png",
        file_size=10,
        title="приложение двойной запрос",
        description="интерфейс приложения",
        tags=["ui", "1С"],
    )
    meme = VisualAsset(
        project_id=project.id,
        type=AssetType.IMAGE,
        status=AssetStatus.READY,
        original_path="meme.png",
        filename="database_meme.png",
        mime_type="image/png",
        file_size=10,
        title="всё сломалось",
        description="мем",
        tags=["meme"],
    )
    session.add_all([source, screenshot, meme])
    await session.commit()
    await VoiceoverService(session).create_from_processed_source(item.id, source.id)
    materials = ProductionMaterialService(session)
    await materials.attach(
        item.id,
        MaterialAttach(asset_id=screenshot.id, roles=[ProductionMaterialRole.SCREENSHOT]),
    )
    meme_material = await materials.attach(
        item.id,
        MaterialAttach(asset_id=meme.id, roles=[ProductionMaterialRole.MEME]),
    )
    settings = Settings()
    assembly = AutoAssemblyService(session, settings)
    first = await assembly.assemble(item.id)
    placement, second = await assembly.insert_locked(
        item.id, meme_material.id, "Поставь его где говорю про всё окончательно сломалось"
    )
    assert placement.status == "unique"
    assert second and second.revision_number == 2
    locked = [
        entry
        for entry in ProductionTimeline.model_validate(second.timeline_json).items
        if entry.locked_by_user
    ]
    assert locked and locked[0].asset_id == meme.id
    third = await assembly.local_replan(item.id, "Первые 3 секунд сделай быстрее. Убери все мемы")
    timeline = ProductionTimeline.model_validate(third.timeline_json)
    assert any(entry.id == locked[0].id for entry in timeline.items)
    rollback = await TimelineRevisionService(session).rollback(item.id, first.id)
    assert rollback.revision_number == 4
    assert len(await TimelineRevisionService(session).history(item.id)) == 4


def test_semantic_placement_unique_ambiguous_and_no_match() -> None:
    voice = type(
        "Voice",
        (),
        {
            "duration": 10.0,
            "alignment": {
                "sections": [
                    {"start": 0, "end": 3, "voice_text": "говорим про 1С"},
                    {"start": 3, "end": 6, "voice_text": "ещё раз говорим про 1С"},
                    {"start": 6, "end": 9, "voice_text": "двойной запрос"},
                ]
            },
            "segments": [],
        },
    )()
    service = SemanticPlacementService()
    assert service.find("после фразы про двойной запрос", voice).status == "unique"
    assert service.find("когда говорю про 1С", voice).status == "ambiguous"
    assert service.find("про космический корабль", voice).status == "no_match"


def test_visual_gaps_and_render_profiles() -> None:
    settings = Settings()
    timeline = ProductionTimeline(
        duration=15,
        voiceover_track_id=uuid.uuid4(),
        items=[
            {
                "track": TimelineTrack.AUDIO_MASTER,
                "start": 0,
                "end": 15,
            },
            {
                "track": TimelineTrack.BROLL,
                "start": 8,
                "end": 15,
                "metadata": {"asset_type": "screenshot"},
            },
        ],
    )
    assert VisualGapAnalyzer(settings).analyze(timeline)
    assert render_profile(settings, "preview").width == 720
    assert render_profile(settings, "final").width == 1080
    assert render_profile(settings, "preview").crf > render_profile(settings, "final").crf


@pytest.mark.asyncio
async def test_runtime_settings_secret_store_owner_security_and_ai_boundary(session) -> None:
    _, user, _ = await production(session)
    settings = Settings(ai_model="env-model")
    service = SettingsService(session, settings)
    assert await service.get("ai_model") == "env-model"
    await service.set("ai_model", "db-model", actor=user)
    assert await service.get("ai_model") == "db-model"
    assert (await service.resolved()).ai_model == "db-model"
    assert await session.scalar(select(RuntimeSetting).where(RuntimeSetting.key == "ai_model"))
    regular = User(telegram_id=99, role=UserRole.USER)
    session.add(regular)
    await session.commit()
    with pytest.raises(InvalidStateError):
        await service.set("ai_model", "bad", actor=regular)
    with pytest.raises(InvalidStateError):
        service.require_owner(user, private_chat=False)
    key = Fernet.generate_key().decode()
    secrets = EncryptedDatabaseSecretStore(session, key)
    await secrets.set(user.id, "ai_api_key", "super-secret")
    row = await session.scalar(select(EncryptedSecret))
    assert row and b"super-secret" not in row.ciphertext
    assert await secrets.get(user.id, "ai_api_key") == "super-secret"

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

    tester = AIConnectionTester(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    result = await tester.test("http://lm-studio.test/v1", "qwen")
    assert result["ok"] is True
    await tester.client.aclose()


def test_asset_roles_and_material_schema_validation() -> None:
    with pytest.raises(ValueError):
        MaterialAttach()
    with pytest.raises(ValueError):
        MaterialAttach(source_item_id=uuid.uuid4(), asset_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_production_relations_are_durable(session) -> None:
    item, _, _ = await production(session)
    loaded = await session.get(ProductionProject, item.id)
    assert loaded and loaded.initial_source_item_id
    assert len(await ProductionMaterialService(session).list(item.id)) == 1
    assert (
        await session.scalar(
            select(ScriptVersion).where(ScriptVersion.production_project_id == item.id)
        )
        is None
    )
    assert (
        await session.scalar(
            select(TimelineRevision).where(TimelineRevision.production_project_id == item.id)
        )
        is None
    )
