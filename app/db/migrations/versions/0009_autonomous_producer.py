"""Add Phase 8 autonomous Producer, research provenance and channel profiles."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_autonomous_producer"
down_revision: str | None = "0008_autonomous_director"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    json_type = postgresql.JSONB() if bind.dialect.name == "postgresql" else sa.JSON()
    now = sa.func.now()

    op.create_table(
        "producer_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("raw_prompt", sa.Text(), nullable=False),
        sa.Column("platform", sa.String(64), nullable=False, server_default="youtube_shorts"),
        sa.Column("target_duration", sa.Float()),
        sa.Column("tone", sa.String(255)),
        sa.Column("research_mode", sa.String(32), nullable=False, server_default="fixtures"),
        sa.Column("approval_mode", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("approval_state", sa.String(32), nullable=False, server_default="not_required"),
        sa.Column("status", sa.String(32), nullable=False, server_default="created"),
        sa.Column("current_stage", sa.String(32), nullable=False, server_default="created"),
        sa.Column("idempotency_key", sa.String(255), unique=True),
        sa.Column("step_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("llm_call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("search_query_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("fetch_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("script_iterations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("artifacts", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("errors", json_type, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("error", sa.Text()),
        sa.Column(
            "production_project_id",
            sa.Uuid(),
            sa.ForeignKey("production_projects.id", ondelete="SET NULL"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_producer_runs_status", "producer_runs", ["status"])
    op.create_index("ix_producer_runs_completed_at", "producer_runs", ["completed_at"])
    op.create_index(
        "ix_producer_runs_idempotency_key", "producer_runs", ["idempotency_key"], unique=True
    )
    op.create_index(
        "ix_producer_runs_project_user_updated",
        "producer_runs",
        ["project_id", "user_id", "updated_at"],
    )

    op.create_table(
        "research_sources",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("producer_runs.id", ondelete="SET NULL")),
        sa.Column("canonical_url", sa.String(2048), nullable=False, unique=True),
        sa.Column("final_url", sa.String(2048)),
        sa.Column("title", sa.String(1000), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column(
            "extractor_version", sa.String(64), nullable=False, server_default="producer-html-v1"
        ),
        sa.Column("content_type", sa.String(255), nullable=False, server_default="text/html"),
        sa.Column("extracted_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("metadata_json", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("time_sensitive", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "prompt_injection_detected", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
    )
    op.create_index(
        "ix_research_sources_canonical_url", "research_sources", ["canonical_url"], unique=True
    )
    op.create_index("ix_research_sources_content_hash", "research_sources", ["content_hash"])
    op.create_index("ix_research_sources_run_id", "research_sources", ["run_id"])

    op.create_table(
        "research_facts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("run_id", sa.Uuid(), sa.ForeignKey("producer_runs.id", ondelete="SET NULL")),
        sa.Column(
            "production_project_id",
            sa.Uuid(),
            sa.ForeignKey("production_projects.id", ondelete="SET NULL"),
        ),
        sa.Column("claim", sa.Text(), nullable=False),
        sa.Column("normalized_claim", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("status", sa.String(32), nullable=False, server_default="verified"),
        sa.Column("critical", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("time_sensitive", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("stale", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("conflict_group", sa.String(128)),
        sa.Column("provenance_json", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
    )
    op.create_index("ix_research_facts_run_id", "research_facts", ["run_id"])
    op.create_index(
        "ix_research_facts_production_project_id", "research_facts", ["production_project_id"]
    )
    op.create_index("ix_research_facts_normalized_claim", "research_facts", ["normalized_claim"])
    op.create_table(
        "research_fact_sources",
        sa.Column(
            "fact_id",
            sa.Uuid(),
            sa.ForeignKey("research_facts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "source_id",
            sa.Uuid(),
            sa.ForeignKey("research_sources.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.UniqueConstraint("fact_id", "source_id", name="uq_research_fact_source"),
    )

    op.create_table(
        "content_channel_profiles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("platform", sa.String(64), nullable=False),
        sa.Column("audience", sa.Text(), nullable=False, server_default=""),
        sa.Column("tone", sa.String(255), nullable=False, server_default=""),
        sa.Column("content_pillars", json_type, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("preferred_duration", sa.Float()),
        sa.Column("cta_strategy", sa.Text(), nullable=False, server_default=""),
        sa.Column("taboo_topics", json_type, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("brand_voice", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.UniqueConstraint(
            "project_id", "platform", name="uq_content_channel_profile_project_platform"
        ),
    )
    op.create_index(
        "ix_content_channel_profiles_project_id", "content_channel_profiles", ["project_id"]
    )


def downgrade() -> None:
    op.drop_table("content_channel_profiles")
    op.drop_table("research_fact_sources")
    op.drop_table("research_facts")
    op.drop_table("research_sources")
    op.drop_table("producer_runs")
