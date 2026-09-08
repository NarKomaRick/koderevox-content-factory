import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Float,
    ForeignKey,
    Integer,
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
    ContentFormat,
    ContentPillar,
    DraftStatus,
    IdeaStatus,
    Platform,
    ProcessingStage,
    SourceStatus,
    SourceType,
    UserRole,
    VideoProjectStatus,
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
    vocabulary: Mapped[list[str]] = mapped_column(JSON_DOCUMENT, default=list)
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
    subtitle_style: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    render_settings: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    transcript_overrides: Mapped[dict[str, str]] = mapped_column(JSON_DOCUMENT, default=dict)
    preview_path: Mapped[str | None] = mapped_column(String(1024))
    final_path: Mapped[str | None] = mapped_column(String(1024))
    render_error: Mapped[str | None] = mapped_column(Text)
    render_task_id: Mapped[str | None] = mapped_column(String(255))
    render_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSON_DOCUMENT, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now_utc)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=now_utc, onupdate=now_utc
    )

    project: Mapped[Project] = relationship()
    source_item: Mapped[SourceItem] = relationship()
    content_draft: Mapped[ContentDraft | None] = relationship()
