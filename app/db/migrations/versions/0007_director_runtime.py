"""Add durable state for the bounded Phase 6 Director runtime."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_director_runtime"
down_revision: str | None = "0006_snowball_production"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = postgresql.JSONB() if op.get_bind().dialect.name == "postgresql" else sa.JSON()
    op.create_table(
        "director_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "production_project_id",
            sa.Uuid(),
            sa.ForeignKey("production_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("director_iteration", sa.Integer(), nullable=False),
        sa.Column("step_count", sa.Integer(), nullable=False),
        sa.Column("llm_call_count", sa.Integer(), nullable=False),
        sa.Column("preview_count", sa.Integer(), nullable=False),
        sa.Column("external_asset_count", sa.Integer(), nullable=False),
        sa.Column("external_asset_bytes", sa.BigInteger(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "current_revision_id",
            sa.Uuid(),
            sa.ForeignKey("timeline_revisions.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "best_revision_id",
            sa.Uuid(),
            sa.ForeignKey("timeline_revisions.id", ondelete="SET NULL"),
        ),
        sa.Column("context_json", json_type, nullable=False),
        sa.Column("history_json", json_type, nullable=False),
        sa.Column("quality_report_json", json_type, nullable=False),
        sa.Column("error", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_director_runs_production_project_id", "director_runs", ["production_project_id"]
    )
    op.create_index("ix_director_runs_status", "director_runs", ["status"])
    op.create_index("ix_director_runs_active", "director_runs", ["active"])

    op.create_table(
        "director_actions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("director_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tool_call_id", sa.String(255), nullable=False),
        sa.Column("step_number", sa.Integer(), nullable=False),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("arguments", json_type, nullable=False),
        sa.Column("result", json_type, nullable=False),
        sa.Column(
            "revision_id",
            sa.Uuid(),
            sa.ForeignKey("timeline_revisions.id", ondelete="SET NULL"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "tool_call_id", name="uq_director_action_call"),
    )
    op.create_index("ix_director_actions_run_id", "director_actions", ["run_id"])


def downgrade() -> None:
    op.drop_table("director_actions")
    op.drop_table("director_runs")
