"""Add Phase 3 video render projects and project vocabulary."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_video_projects"
down_revision: str | None = "0002_content_inbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = postgresql.JSONB() if op.get_bind().dialect.name == "postgresql" else sa.JSON()
    op.add_column(
        "projects",
        sa.Column("vocabulary", json_type, nullable=False, server_default=sa.text("'[]'")),
    )
    op.execute(
        sa.text(
            "UPDATE projects SET vocabulary = "
            '\'["Koderevox", "BestWay", "Altair", "REST API", "1С", '
            '"React Native", "Swift", "Kotlin", "PostgreSQL", "FastAPI", "LLM"]\''
        )
    )
    op.create_table(
        "video_projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column(
            "source_item_id",
            sa.Uuid(),
            sa.ForeignKey("source_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "content_draft_id",
            sa.Uuid(),
            sa.ForeignKey("content_drafts.id", ondelete="SET NULL"),
        ),
        sa.Column("format", sa.String(32), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "analyzing",
                "ready_to_render",
                "rendering",
                "rendered",
                "approved",
                "cancel_requested",
                "failed",
                "archived",
                name="videoprojectstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("target_duration", sa.Float(), nullable=False),
        sa.Column("aspect_ratio", sa.String(16), nullable=False),
        sa.Column("source_start", sa.Float()),
        sa.Column("source_end", sa.Float()),
        sa.Column("concepts", json_type, nullable=False),
        sa.Column("selected_concept", sa.Integer()),
        sa.Column("edit_plan", json_type, nullable=False),
        sa.Column("subtitle_style", json_type, nullable=False),
        sa.Column("render_settings", json_type, nullable=False),
        sa.Column("transcript_overrides", json_type, nullable=False),
        sa.Column("preview_path", sa.String(1024)),
        sa.Column("final_path", sa.String(1024)),
        sa.Column("render_error", sa.Text()),
        sa.Column("render_task_id", sa.String(255)),
        sa.Column("render_fingerprint", sa.String(64)),
        sa.Column("metrics", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_video_projects_project_id", "video_projects", ["project_id"])
    op.create_index("ix_video_projects_source_item_id", "video_projects", ["source_item_id"])
    op.create_index("ix_video_projects_content_draft_id", "video_projects", ["content_draft_id"])
    op.create_index(
        "ix_video_projects_render_fingerprint", "video_projects", ["render_fingerprint"]
    )


def downgrade() -> None:
    op.drop_table("video_projects")
    op.drop_column("projects", "vocabulary")
