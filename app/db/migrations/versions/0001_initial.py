"""Initial content factory schema and Koderevox seed."""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID

import sqlalchemy as sa
from alembic import op

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

KODEREVOX_ID = UUID("54ae19ee-2fa8-4ef7-bcaf-f8d27028d39a")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(255)),
        sa.Column("role", sa.String(5), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("telegram_id"),
    )
    op.create_index("ix_users_telegram_id", "users", ["telegram_id"])
    op.create_table(
        "projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("brand_context", sa.Text(), nullable=False),
        sa.Column("target_audience", sa.Text(), nullable=False),
        sa.Column("language", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "source_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("type", sa.String(8), nullable=False),
        sa.Column("original_text", sa.Text()),
        sa.Column("transcript", sa.Text()),
        sa.Column("telegram_file_id", sa.String(512)),
        sa.Column("local_file_path", sa.String(1024)),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("processing_status", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_source_items_project_id", "source_items", ["project_id"])
    op.create_index("ix_source_items_user_id", "source_items", ["user_id"])
    op.create_table(
        "content_ideas",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("source_item_id", sa.Uuid(), sa.ForeignKey("source_items.id")),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("angle", sa.Text(), nullable=False),
        sa.Column("suggested_hook", sa.Text(), nullable=False),
        sa.Column("suggested_format", sa.String(11), nullable=False),
        sa.Column("estimated_duration", sa.Integer(), nullable=False),
        sa.Column("target_audience", sa.Text(), nullable=False),
        sa.Column("content_pillar", sa.String(18), nullable=False),
        sa.Column("status", sa.String(8), nullable=False),
        sa.Column("score", sa.Float()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_content_ideas_project_id", "content_ideas", ["project_id"])
    op.create_index("ix_content_ideas_source_item_id", "content_ideas", ["source_item_id"])
    op.create_table(
        "content_drafts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("idea_id", sa.Uuid(), sa.ForeignKey("content_ideas.id"), nullable=False),
        sa.Column("platform", sa.String(14), nullable=False),
        sa.Column("format", sa.String(11), nullable=False),
        sa.Column("hook", sa.Text(), nullable=False),
        sa.Column("script", sa.Text(), nullable=False),
        sa.Column("scene_breakdown", sa.JSON(), nullable=False),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("call_to_action", sa.Text(), nullable=False),
        sa.Column("estimated_duration", sa.Integer()),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("llm_metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_content_drafts_idea_id", "content_drafts", ["idea_id"])

    projects = sa.table(
        "projects",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("brand_context", sa.Text()),
        sa.column("target_audience", sa.Text()),
        sa.column("language", sa.String()),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    now = datetime.now(UTC)
    op.bulk_insert(
        projects,
        [
            {
                "id": KODEREVOX_ID,
                "name": "Koderevox",
                "description": "Студия разработки цифровых продуктов.",
                "brand_context": (
                    "Koderevox разрабатывает мобильные приложения Android и iOS, CRM, сайты, "
                    "backend, REST API, интеграции с 1С, AI и автоматизацию. Есть опыт нативных "
                    "приложений для федеральной сети автосервисов BestWay и приложения записи "
                    "детей на тренировки для сети Altair. Позиционирование: современная инженерная "
                    "студия, не инфобизнес. Тон компетентный, человеческий и технически грамотный. "
                    "Без AI-slop, пафоса, канцелярита, бессмысленных эмодзи и пустого кликбейта."
                ),
                "target_audience": (
                    "Владельцы бизнеса, продуктовые команды и технические руководители, которым "
                    "нужна разработка или интеграция цифровых продуктов."
                ),
                "language": "ru",
                "created_at": now,
                "updated_at": now,
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("content_drafts")
    op.drop_table("content_ideas")
    op.drop_table("source_items")
    op.drop_table("projects")
    op.drop_table("users")
