import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import Enum as SAEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import (
    AssetStatus,
    AssetType,
    ContentFormat,
    ContentPillar,
    DraftStatus,
    IdeaStatus,
    Platform,
    ProcessingStage,
    ProductionFactStatus,
    ProductionStatus,
    PublicationAttemptStatus,
    PublicationEventType,
    PublicationStatus,
    PublishingPlatform,
    PublishPackageStatus,
    ScriptSource,
    SourceStatus,
    SourceType,
    ThumbnailStatus,
    UserRole,
    VideoProjectStatus,
    VoiceoverStatus,
)


def now_utc() -> datetime:
    return datetime.now(UTC)


def enum_column(enum_type: type, default: object) -> Mapped[Any]:
    return mapped_column(
        SAEnum(
            enum_type,
            native_enum=False,
            values_callable=lambda values: [value.value for value in values],
        ),
        default=default,
    )


JSON_DOCUMENT = JSON().with_variant(JSONB, "postgresql")


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True)
    username: Mapped[str | None] = mapped_column(String(255))
    role: Mapped[UserRole] = enum_column(UserRole, UserRole.USER)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(255), unique=True)
    description: Mapped[str] = mapped_column(Text, default="")
    brand_context: Mapped[str] = mapped_column(Text, default="")
    target_audience: Mapped[str] = mapped_column(Text, default="")
    language: Mapped[str] = mapped_column(String(16), default="ru")
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Moscow")
    vocabulary: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    allow_external_vision: Mapped[bool] = mapped_column(default=False)
    brand_preset: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )


class SourceItem(Base):
    __tablename__ = "source_items"
    __table_args__ = (
        UniqueConstraint(
            "telegram_chat_id", "telegram_message_id", name="uq_source_telegram_message"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    type: Mapped[SourceType] = enum_column(SourceType, SourceType.TEXT)
    original_text: Mapped[str | None] = mapped_column(Text)
    transcript: Mapped[str | None] = mapped_column(Text)
    telegram_file_id: Mapped[str | None] = mapped_column(String(512))
    telegram_unique_file_id: Mapped[str | None] = mapped_column(String(512), index=True)
    telegram_chat_id: Mapped[int | None] = mapped_column(BigInteger)
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger)
    telegram_update_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    local_file_path: Mapped[str | None] = mapped_column(String(1024))
    processed_file_path: Mapped[str | None] = mapped_column(String(1024))
    mime_type: Mapped[str | None] = mapped_column(String(255))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    original_filename: Mapped[str | None] = mapped_column(String(512))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    source_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    processing_status: Mapped[SourceStatus] = enum_column(SourceStatus, SourceStatus.NEW)
    processing_stage: Mapped[ProcessingStage] = enum_column(
        ProcessingStage, ProcessingStage.RECEIVED
    )
    processing_error: Mapped[str | None] = mapped_column(Text)
    transcript_language: Mapped[str | None] = mapped_column(String(16))
    transcript_segments: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    topic: Mapped[str | None] = mapped_column(String(500), index=True)
    content_potential_score: Mapped[int | None] = mapped_column(Integer, index=True)
    content_analysis: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    project: Mapped[Project] = relationship()
    user: Mapped[User] = relationship()
    notes: Mapped[list["SourceNote"]] = relationship(
        back_populates="source", cascade="all, delete-orphan", order_by="SourceNote.created_at"
    )


class SourceNote(Base):
    __tablename__ = "source_notes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_items.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    text: Mapped[str | None] = mapped_column(Text)
    transcript: Mapped[str | None] = mapped_column(Text)
    telegram_file_id: Mapped[str | None] = mapped_column(String(512))
    telegram_unique_file_id: Mapped[str | None] = mapped_column(String(512))
    telegram_update_id: Mapped[int | None] = mapped_column(BigInteger, unique=True)
    local_file_path: Mapped[str | None] = mapped_column(String(1024))
    mime_type: Mapped[str | None] = mapped_column(String(255))
    file_size: Mapped[int | None] = mapped_column(BigInteger)
    note_metadata: Mapped[dict[str, Any]] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    source: Mapped[SourceItem] = relationship(back_populates="notes")
    user: Mapped[User] = relationship()


class ContentIdea(Base):
    __tablename__ = "content_ideas"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    source_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_items.id"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text)
    angle: Mapped[str] = mapped_column(Text)
    suggested_hook: Mapped[str] = mapped_column(Text)
    suggested_format: Mapped[ContentFormat] = enum_column(ContentFormat, ContentFormat.SHORT_VIDEO)
    estimated_duration: Mapped[int] = mapped_column(default=45)
    target_audience: Mapped[str] = mapped_column(Text)
    content_pillar: Mapped[ContentPillar] = enum_column(ContentPillar, ContentPillar.EDUCATION)
    status: Mapped[IdeaStatus] = enum_column(IdeaStatus, IdeaStatus.DRAFT)
    score: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    project: Mapped[Project] = relationship()
    source_item: Mapped[SourceItem | None] = relationship()


class ContentDraft(Base):
    __tablename__ = "content_drafts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    idea_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("content_ideas.id"), index=True)
    platform: Mapped[Platform] = enum_column(Platform, Platform.YOUTUBE_SHORTS)
    format: Mapped[ContentFormat] = enum_column(ContentFormat, ContentFormat.SHORT_VIDEO)
    hook: Mapped[str] = mapped_column(Text)
    script: Mapped[str] = mapped_column(Text)
    scene_breakdown: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    caption: Mapped[str] = mapped_column(Text, default="")
    title: Mapped[str] = mapped_column(String(500))
    description: Mapped[str] = mapped_column(Text, default="")
    call_to_action: Mapped[str] = mapped_column(Text, default="")
    estimated_duration: Mapped[int | None]
    status: Mapped[DraftStatus] = enum_column(DraftStatus, DraftStatus.GENERATING)
    llm_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    idea: Mapped[ContentIdea] = relationship()


class VideoProject(Base):
    __tablename__ = "video_projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    source_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_items.id", ondelete="CASCADE"), index=True
    )
    content_draft_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("content_drafts.id", ondelete="SET NULL"), index=True
    )
    format: Mapped[str] = mapped_column(String(32), default="short_video")
    status: Mapped[VideoProjectStatus] = enum_column(VideoProjectStatus, VideoProjectStatus.DRAFT)
    target_duration: Mapped[float] = mapped_column(Float, default=45.0)
    aspect_ratio: Mapped[str] = mapped_column(String(16), default="9:16")
    source_start: Mapped[float | None] = mapped_column(Float)
    source_end: Mapped[float | None] = mapped_column(Float)
    concepts: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, default=list)
    selected_concept: Mapped[int | None] = mapped_column(Integer)
    edit_plan: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    visual_plan: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    subtitle_style: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    render_settings: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    transcript_overrides: Mapped[dict[str, str]] = mapped_column(JSON_DOCUMENT, default=dict)
    preview_path: Mapped[str | None] = mapped_column(String(1024))
    final_path: Mapped[str | None] = mapped_column(String(1024))
    render_error: Mapped[str | None] = mapped_column(Text)
    render_task_id: Mapped[str | None] = mapped_column(String(255))
    render_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    selected_thumbnail_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    project: Mapped[Project] = relationship()
    source_item: Mapped[SourceItem] = relationship()
    content_draft: Mapped[ContentDraft | None] = relationship()


class VisualAsset(Base):
    __tablename__ = "visual_assets"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    source_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_items.id", ondelete="SET NULL"), index=True
    )
    parent_asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("visual_assets.id", ondelete="SET NULL"), index=True
    )
    type: Mapped[AssetType] = enum_column(AssetType, AssetType.IMAGE)
    status: Mapped[AssetStatus] = enum_column(AssetStatus, AssetStatus.PROCESSING)
    original_path: Mapped[str] = mapped_column(String(1024))
    processed_path: Mapped[str | None] = mapped_column(String(1024))
    thumbnail_path: Mapped[str | None] = mapped_column(String(1024))
    filename: Mapped[str] = mapped_column(String(512))
    mime_type: Mapped[str] = mapped_column(String(255))
    file_size: Mapped[int] = mapped_column(BigInteger)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration: Mapped[float | None] = mapped_column(Float)
    title: Mapped[str] = mapped_column(String(500), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    tags: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    extracted_text: Mapped[str | None] = mapped_column(Text)
    analysis: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    favorite: Mapped[bool] = mapped_column(default=False, index=True)
    license_type: Mapped[str | None] = mapped_column(String(100))
    source: Mapped[str | None] = mapped_column(String(1024))
    author: Mapped[str | None] = mapped_column(String(255))
    attribution_required: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    project: Mapped[Project] = relationship()
    source_item: Mapped[SourceItem | None] = relationship()
    parent_asset: Mapped["VisualAsset | None"] = relationship(remote_side="VisualAsset.id")


class AssetUsage(Base):
    __tablename__ = "asset_usages"
    __table_args__ = (
        UniqueConstraint(
            "asset_id",
            "video_project_id",
            "start",
            "end",
            "usage_type",
            name="uq_asset_usage_timeline",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    asset_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("visual_assets.id", ondelete="CASCADE"), index=True
    )
    video_project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("video_projects.id", ondelete="CASCADE"), index=True
    )
    start: Mapped[float] = mapped_column(Float)
    end: Mapped[float] = mapped_column(Float)
    usage_type: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    asset: Mapped[VisualAsset] = relationship()
    video_project: Mapped[VideoProject] = relationship()


class ThumbnailProject(Base):
    __tablename__ = "thumbnail_projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    video_project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("video_projects.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[ThumbnailStatus] = enum_column(ThumbnailStatus, ThumbnailStatus.DRAFT)
    concept: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    render_settings: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    output_path: Mapped[str | None] = mapped_column(String(1024))
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    render_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    project: Mapped[Project] = relationship()
    video_project: Mapped[VideoProject] = relationship()


class ProductionProject(Base):
    __tablename__ = "production_projects"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), index=True)
    initial_source_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_items.id", ondelete="SET NULL"), index=True
    )
    title: Mapped[str] = mapped_column(String(500))
    working_title: Mapped[str] = mapped_column(String(500), default="")
    status: Mapped[ProductionStatus] = enum_column(ProductionStatus, ProductionStatus.IDEA)
    target_format: Mapped[str] = mapped_column(String(64), default="short_video")
    target_duration: Mapped[float | None] = mapped_column(Float)
    current_script_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    approved_script_version_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    primary_voiceover_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    active_video_project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("video_projects.id", ondelete="SET NULL"), index=True
    )
    active_timeline_revision_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, index=True)
    production_context: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    persistent_instructions: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    project: Mapped[Project] = relationship()
    user: Mapped[User] = relationship()
    initial_source_item: Mapped[SourceItem | None] = relationship()
    active_video_project: Mapped[VideoProject | None] = relationship()


class ProductionMaterial(Base):
    __tablename__ = "production_materials"
    __table_args__ = (
        UniqueConstraint(
            "production_project_id", "source_item_id", name="uq_production_material_source"
        ),
        UniqueConstraint("production_project_id", "asset_id", name="uq_production_material_asset"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    production_project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("production_projects.id", ondelete="CASCADE"), index=True
    )
    source_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_items.id", ondelete="SET NULL"), index=True
    )
    asset_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("visual_assets.id", ondelete="SET NULL"), index=True
    )
    roles: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    user_instruction: Mapped[str | None] = mapped_column(Text)
    is_user_locked: Mapped[bool] = mapped_column(Boolean, default=False)
    is_used: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    production_project: Mapped[ProductionProject] = relationship()
    source_item: Mapped[SourceItem | None] = relationship()
    asset: Mapped[VisualAsset | None] = relationship()


class ProductionFact(Base):
    __tablename__ = "production_facts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    production_project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("production_projects.id", ondelete="CASCADE"), index=True
    )
    text: Mapped[str] = mapped_column(Text)
    source_item_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("source_items.id", ondelete="SET NULL"), index=True
    )
    source_url: Mapped[str | None] = mapped_column(String(2048))
    status: Mapped[ProductionFactStatus] = enum_column(
        ProductionFactStatus, ProductionFactStatus.PROPOSED
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )


class ScriptVersion(Base):
    __tablename__ = "script_versions"
    __table_args__ = (
        UniqueConstraint(
            "production_project_id", "version_number", name="uq_script_project_version"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    production_project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("production_projects.id", ondelete="CASCADE"), index=True
    )
    version_number: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)
    structured_sections: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, default=list)
    source: Mapped[ScriptSource] = enum_column(ScriptSource, ScriptSource.AI)
    user_instruction: Mapped[str | None] = mapped_column(Text)
    diff: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class VoiceoverTrack(Base):
    __tablename__ = "voiceover_tracks"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    production_project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("production_projects.id", ondelete="CASCADE"), index=True
    )
    source_item_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_items.id", ondelete="RESTRICT"), index=True
    )
    original_path: Mapped[str] = mapped_column(String(1024))
    processed_path: Mapped[str] = mapped_column(String(1024))
    duration: Mapped[float] = mapped_column(Float)
    language: Mapped[str | None] = mapped_column(String(16))
    transcript: Mapped[str] = mapped_column(Text)
    segments: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, default=list)
    words: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, default=list)
    script_version_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("script_versions.id", ondelete="SET NULL"), index=True
    )
    alignment: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    alignment_score: Mapped[float | None] = mapped_column(Float)
    status: Mapped[VoiceoverStatus] = enum_column(VoiceoverStatus, VoiceoverStatus.PROCESSING)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )


class TimelineRevision(Base):
    __tablename__ = "timeline_revisions"
    __table_args__ = (
        UniqueConstraint(
            "production_project_id", "revision_number", name="uq_timeline_project_revision"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    production_project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("production_projects.id", ondelete="CASCADE"), index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer)
    timeline_json: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    user_instruction: Mapped[str | None] = mapped_column(Text)
    change_summary: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class DirectorRun(Base):
    """Durable state for one bounded Director orchestration run."""

    __tablename__ = "director_runs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    production_project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("production_projects.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    instruction: Mapped[str] = mapped_column(Text, default="")
    director_iteration: Mapped[int] = mapped_column(Integer, default=0)
    step_count: Mapped[int] = mapped_column(Integer, default=0)
    llm_call_count: Mapped[int] = mapped_column(Integer, default=0)
    preview_count: Mapped[int] = mapped_column(Integer, default=0)
    external_asset_count: Mapped[int] = mapped_column(Integer, default=0)
    external_asset_bytes: Mapped[int] = mapped_column(BigInteger, default=0)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    current_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("timeline_revisions.id", ondelete="SET NULL")
    )
    best_revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("timeline_revisions.id", ondelete="SET NULL")
    )
    context_json: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    history_json: Mapped[list[dict[str, Any]]] = mapped_column(JSON_DOCUMENT, default=list)
    quality_report_json: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )


class DirectorAction(Base):
    """An idempotent, inspectable record of a Director tool call."""

    __tablename__ = "director_actions"
    __table_args__ = (UniqueConstraint("run_id", "tool_call_id", name="uq_director_action_call"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("director_runs.id", ondelete="CASCADE"), index=True
    )
    tool_call_id: Mapped[str] = mapped_column(String(255))
    step_number: Mapped[int] = mapped_column(Integer)
    tool_name: Mapped[str] = mapped_column(String(100))
    arguments: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    result: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    revision_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("timeline_revisions.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class RuntimeSetting(Base):
    __tablename__ = "runtime_settings"
    __table_args__ = (
        UniqueConstraint("scope", "scope_id", "key", name="uq_runtime_setting_scope_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    scope: Mapped[str] = mapped_column(String(32), default="system")
    scope_id: Mapped[uuid.UUID | None] = mapped_column(Uuid)
    key: Mapped[str] = mapped_column(String(255), index=True)
    value: Mapped[Any] = mapped_column(JSON_DOCUMENT)
    updated_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )


class EncryptedSecret(Base):
    __tablename__ = "encrypted_secrets"
    __table_args__ = (
        UniqueConstraint("owner_user_id", "name", name="uq_encrypted_secret_owner_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    ciphertext: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )


class PublishPackage(Base):
    __tablename__ = "publish_packages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    content_draft_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("content_drafts.id", ondelete="SET NULL"), index=True
    )
    video_project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("video_projects.id", ondelete="SET NULL"), unique=True, index=True
    )
    thumbnail_project_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("thumbnail_projects.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[PublishPackageStatus] = enum_column(
        PublishPackageStatus, PublishPackageStatus.DRAFT
    )
    master_video_path: Mapped[str | None] = mapped_column(String(1024))
    master_thumbnail_path: Mapped[str | None] = mapped_column(String(1024))
    base_title: Mapped[str] = mapped_column(String(500), default="")
    base_caption: Mapped[str] = mapped_column(Text, default="")
    base_description: Mapped[str] = mapped_column(Text, default="")
    package_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_DOCUMENT, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    project: Mapped[Project] = relationship()
    content_draft: Mapped[ContentDraft | None] = relationship()
    video_project: Mapped[VideoProject | None] = relationship()
    thumbnail_project: Mapped[ThumbnailProject | None] = relationship()
    variants: Mapped[list["PlatformVariant"]] = relationship(
        back_populates="publish_package", cascade="all, delete-orphan"
    )


class PlatformVariant(Base):
    __tablename__ = "platform_variants"
    __table_args__ = (
        UniqueConstraint("publish_package_id", "platform", name="uq_variant_package_platform"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    publish_package_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("publish_packages.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[PublishingPlatform] = enum_column(
        PublishingPlatform, PublishingPlatform.TELEGRAM
    )
    video_path: Mapped[str | None] = mapped_column(String(1024))
    thumbnail_path: Mapped[str | None] = mapped_column(String(1024))
    title: Mapped[str] = mapped_column(String(500), default="")
    caption: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    hashtags: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    media_profile: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    publish_package: Mapped[PublishPackage] = relationship(back_populates="variants")


class PlatformAccount(Base):
    __tablename__ = "platform_accounts"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "platform", "display_name", name="uq_account_project_platform_name"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    platform: Mapped[PublishingPlatform] = enum_column(
        PublishingPlatform, PublishingPlatform.TELEGRAM
    )
    display_name: Mapped[str] = mapped_column(String(255))
    external_account_id: Mapped[str | None] = mapped_column(String(512))
    username: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    capabilities: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    project: Mapped[Project] = relationship()


class EncryptedCredential(Base):
    __tablename__ = "encrypted_credentials"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    platform_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform_accounts.id", ondelete="CASCADE"), unique=True, index=True
    )
    encrypted_payload: Mapped[bytes] = mapped_column(LargeBinary)
    key_version: Mapped[int] = mapped_column(Integer, default=1)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    platform_account: Mapped[PlatformAccount] = relationship()


class Publication(Base):
    __tablename__ = "publications"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    publish_package_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("publish_packages.id", ondelete="CASCADE"), index=True
    )
    platform_variant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform_variants.id"), index=True
    )
    platform_account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform_accounts.id"), index=True
    )
    platform: Mapped[PublishingPlatform] = enum_column(
        PublishingPlatform, PublishingPlatform.TELEGRAM
    )
    status: Mapped[PublicationStatus] = enum_column(PublicationStatus, PublicationStatus.DRAFT)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remote_id: Mapped[str | None] = mapped_column(String(512), index=True)
    remote_url: Mapped[str | None] = mapped_column(String(2048))
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error_code: Mapped[str | None] = mapped_column(String(100))
    last_error_message: Mapped[str | None] = mapped_column(Text)
    publication_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_DOCUMENT, default=dict
    )
    variant_snapshot: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    variant_hash: Mapped[str] = mapped_column(String(64))
    media_hash: Mapped[str | None] = mapped_column(String(64), index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(255), unique=True, index=True)
    task_id: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    publish_package: Mapped[PublishPackage] = relationship()
    platform_variant: Mapped[PlatformVariant] = relationship()
    platform_account: Mapped[PlatformAccount] = relationship()
    attempts: Mapped[list["PublicationAttempt"]] = relationship(
        back_populates="publication", cascade="all, delete-orphan"
    )
    events: Mapped[list["PublicationEvent"]] = relationship(
        back_populates="publication", cascade="all, delete-orphan"
    )


class PublicationAttempt(Base):
    __tablename__ = "publication_attempts"
    __table_args__ = (
        UniqueConstraint("publication_id", "attempt_number", name="uq_attempt_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    publication_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("publications.id", ondelete="CASCADE"), index=True
    )
    attempt_number: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[PublicationAttemptStatus] = enum_column(
        PublicationAttemptStatus, PublicationAttemptStatus.STARTED
    )
    provider_error_code: Mapped[str | None] = mapped_column(String(255))
    sanitized_error: Mapped[str | None] = mapped_column(Text)
    provider_request_id: Mapped[str | None] = mapped_column(String(512))
    media_hash: Mapped[str | None] = mapped_column(String(64))
    attempt_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSON_DOCUMENT, default=dict
    )

    publication: Mapped[Publication] = relationship(back_populates="attempts")


class PublicationEvent(Base):
    __tablename__ = "publication_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    publication_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("publications.id", ondelete="CASCADE"), index=True
    )
    event_type: Mapped[PublicationEventType] = enum_column(
        PublicationEventType, PublicationEventType.CREATED
    )
    details: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)

    publication: Mapped[Publication] = relationship(back_populates="events")


class OAuthState(Base):
    __tablename__ = "oauth_states"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    state_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    platform: Mapped[PublishingPlatform] = enum_column(
        PublishingPlatform, PublishingPlatform.YOUTUBE
    )
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), index=True)
    platform_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform_accounts.id", ondelete="CASCADE"), index=True
    )
    redirect_after: Mapped[str | None] = mapped_column(String(1024))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)


class WebhookReceipt(Base):
    __tablename__ = "webhook_receipts"
    __table_args__ = (
        UniqueConstraint("platform", "external_event_id", name="uq_webhook_external_event"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    platform: Mapped[PublishingPlatform] = enum_column(
        PublishingPlatform, PublishingPlatform.TIKTOK
    )
    external_event_id: Mapped[str] = mapped_column(String(512))
    payload_hash: Mapped[str] = mapped_column(String(64))
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
