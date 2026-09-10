"""Persist Phase 7 intelligence, variants and preference signals."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008_autonomous_director"
down_revision: str | None = "0007_director_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    json_type = postgresql.JSONB() if bind.dialect.name == "postgresql" else sa.JSON()
    for name in (
        "story_analysis_json",
        "director_plan_json",
        "audio_intelligence_json",
        "metrics_json",
    ):
        op.add_column(
            "director_runs",
            sa.Column(name, json_type, nullable=False, server_default=sa.text("'{}'")),
        )
    op.add_column(
        "director_runs",
        sa.Column("review_iterations", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "director_runs",
        sa.Column("variant_count", sa.Integer(), nullable=False, server_default="0"),
    )

    op.create_table(
        "director_variants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Uuid(),
            sa.ForeignKey("director_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "base_revision_id",
            sa.Uuid(),
            sa.ForeignKey("timeline_revisions.id", ondelete="SET NULL"),
        ),
        sa.Column("variant_key", sa.String(32), nullable=False),
        sa.Column("start", sa.Float(), nullable=False),
        sa.Column("end", sa.Float(), nullable=False),
        sa.Column("goal", sa.String(1000), nullable=False),
        sa.Column("timeline_json", json_type, nullable=False),
        sa.Column("quality_json", json_type, nullable=False),
        sa.Column("selected", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("run_id", "variant_key", name="uq_director_variant_key"),
    )
    op.create_index("ix_director_variants_run_id", "director_variants", ["run_id"])

    op.create_table(
        "director_preferences",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("scope", sa.String(16), nullable=False),
        sa.Column("owner_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="CASCADE")),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("value", sa.String(512), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "scope", "owner_id", "project_id", "key", name="uq_director_preference_owner"
        ),
    )
    op.create_index("ix_director_preferences_owner_id", "director_preferences", ["owner_id"])
    op.create_index("ix_director_preferences_project_id", "director_preferences", ["project_id"])


def downgrade() -> None:
    op.drop_table("director_preferences")
    op.drop_table("director_variants")
    for name in (
        "variant_count",
        "review_iterations",
        "metrics_json",
        "audio_intelligence_json",
        "director_plan_json",
        "story_analysis_json",
    ):
        op.drop_column("director_runs", name)
