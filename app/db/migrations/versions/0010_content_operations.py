"""Add Phase 9 content operations and studio orchestration state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010_content_operations"
down_revision: str | None = "0009_autonomous_producer"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    json_type = postgresql.JSONB() if bind.dialect.name == "postgresql" else sa.JSON()
    now = sa.func.now()

    op.create_table(
        "content_strategies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column(
            "channel_profile_id",
            sa.Uuid(),
            sa.ForeignKey("content_channel_profiles.id", ondelete="SET NULL"),
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False, server_default=""),
        sa.Column("default_platforms", json_type, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("default_duration", sa.Float(), nullable=False, server_default="60"),
        sa.Column("weekly_target", sa.Integer(), nullable=False, server_default="3"),
        sa.Column(
            "approval_policy", sa.String(32), nullable=False, server_default="before_publish"
        ),
        sa.Column("autonomous_mode", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("auto_publish", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Europe/Moscow"),
        sa.Column("recurrence_rule", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("budget", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
    )
    op.create_index("ix_content_strategies_project_id", "content_strategies", ["project_id"])
    op.create_index("ix_content_strategies_user_id", "content_strategies", ["user_id"])
    op.create_index("ix_content_strategies_enabled", "content_strategies", ["enabled"])
    op.create_index("ix_content_strategies_paused", "content_strategies", ["paused"])

    op.create_table(
        "content_strategy_pillars",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "strategy_id",
            sa.Uuid(),
            sa.ForeignKey("content_strategies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False, server_default="0.25"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("minimum_gap_days", sa.Integer(), nullable=False, server_default="0"),
        sa.UniqueConstraint("strategy_id", "name", name="uq_strategy_pillar_name"),
    )
    op.create_index(
        "ix_content_strategy_pillars_strategy_id", "content_strategy_pillars", ["strategy_id"]
    )

    op.create_table(
        "content_series",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "strategy_id",
            sa.Uuid(),
            sa.ForeignKey("content_strategies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("sequence_mode", sa.String(32), nullable=False, server_default="ordered"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
    )
    op.create_index("ix_content_series_strategy_id", "content_series", ["strategy_id"])

    op.create_table(
        "content_campaigns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "strategy_id",
            sa.Uuid(),
            sa.ForeignKey("content_strategies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("goal", sa.Text(), nullable=False, server_default=""),
        sa.Column("starts_at", sa.DateTime(timezone=True)),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("target_content_count", sa.Integer()),
        sa.Column("allowed_pillars", json_type, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("instructions", json_type, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("paused", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
    )
    op.create_index("ix_content_campaigns_strategy_id", "content_campaigns", ["strategy_id"])
    op.create_index("ix_content_campaigns_starts_at", "content_campaigns", ["starts_at"])
    op.create_index("ix_content_campaigns_ends_at", "content_campaigns", ["ends_at"])

    op.create_table(
        "content_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "strategy_id",
            sa.Uuid(),
            sa.ForeignKey("content_strategies.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.Uuid(),
            sa.ForeignKey("projects.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
        ),
        sa.Column(
            "campaign_id", sa.Uuid(), sa.ForeignKey("content_campaigns.id", ondelete="SET NULL")
        ),
        sa.Column("series_id", sa.Uuid(), sa.ForeignKey("content_series.id", ondelete="SET NULL")),
        sa.Column("series_position", sa.Integer()),
        sa.Column("title_hint", sa.String(500)),
        sa.Column("topic_hint", sa.Text()),
        sa.Column("pillar", sa.String(128)),
        sa.Column("status", sa.String(40), nullable=False, server_default="planned"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="50"),
        sa.Column("manual_priority", sa.String(16), nullable=False, server_default="normal"),
        sa.Column("scheduled_for", sa.DateTime(timezone=True)),
        sa.Column("publish_not_before", sa.DateTime(timezone=True)),
        sa.Column("publish_before", sa.DateTime(timezone=True)),
        sa.Column("target_platforms", json_type, nullable=False, server_default=sa.text("'[]'")),
        sa.Column(
            "producer_run_id", sa.Uuid(), sa.ForeignKey("producer_runs.id", ondelete="SET NULL")
        ),
        sa.Column(
            "production_project_id",
            sa.Uuid(),
            sa.ForeignKey("production_projects.id", ondelete="SET NULL"),
        ),
        sa.Column("approval_state", sa.String(32), nullable=False, server_default="not_required"),
        sa.Column("blocked_reason", sa.String(255)),
        sa.Column("operator_notes", json_type, nullable=False, server_default=sa.text("'[]'")),
        sa.Column("locked", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("lock_reason", sa.String(64)),
        sa.Column("correction_instruction", sa.Text()),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_stage", sa.String(40)),
        sa.Column("failure_report", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("resource_estimate", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column(
            "replaces_content_item_id",
            sa.Uuid(),
            sa.ForeignKey("content_items.id", ondelete="SET NULL"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    for name, columns in {
        "ix_content_items_strategy_id": ["strategy_id"],
        "ix_content_items_project_id": ["project_id"],
        "ix_content_items_user_id": ["user_id"],
        "ix_content_items_campaign_id": ["campaign_id"],
        "ix_content_items_series_id": ["series_id"],
        "ix_content_items_pillar": ["pillar"],
        "ix_content_items_status": ["status"],
        "ix_content_items_priority": ["priority"],
        "ix_content_items_scheduled_for": ["scheduled_for"],
        "ix_content_items_publish_before": ["publish_before"],
        "ix_content_items_producer_run_id": ["producer_run_id"],
        "ix_content_items_production_project_id": ["production_project_id"],
        "ix_content_items_locked": ["locked"],
        "ix_content_items_updated_at": ["updated_at"],
    }.items():
        op.create_index(name, "content_items", columns)

    op.create_table(
        "content_dependencies",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "content_item_id",
            sa.Uuid(),
            sa.ForeignKey("content_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "depends_on_item_id",
            sa.Uuid(),
            sa.ForeignKey("content_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("reason", sa.String(255), nullable=False, server_default=""),
        sa.UniqueConstraint("content_item_id", "depends_on_item_id", name="uq_content_dependency"),
    )
    op.create_index(
        "ix_content_dependencies_content_item_id", "content_dependencies", ["content_item_id"]
    )
    op.create_index(
        "ix_content_dependencies_depends_on_item_id", "content_dependencies", ["depends_on_item_id"]
    )

    op.create_table(
        "approval_requests",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "content_item_id",
            sa.Uuid(),
            sa.ForeignKey("content_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("checkpoint", sa.String(32), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("responded_at", sa.DateTime(timezone=True)),
        sa.Column("actor_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("comment", sa.Text()),
        sa.UniqueConstraint("content_item_id", "checkpoint", name="uq_content_approval_checkpoint"),
    )
    op.create_index(
        "ix_approval_requests_content_item_id", "approval_requests", ["content_item_id"]
    )
    op.create_index("ix_approval_requests_status", "approval_requests", ["status"])

    op.create_table(
        "operations_audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id", ondelete="SET NULL")),
        sa.Column(
            "strategy_id", sa.Uuid(), sa.ForeignKey("content_strategies.id", ondelete="SET NULL")
        ),
        sa.Column(
            "content_item_id", sa.Uuid(), sa.ForeignKey("content_items.id", ondelete="SET NULL")
        ),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("rationale", sa.String(2000), nullable=False, server_default=""),
        sa.Column("data", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
    )
    op.create_index(
        "ix_operations_audit_events_project_id", "operations_audit_events", ["project_id"]
    )
    op.create_index(
        "ix_operations_audit_events_strategy_id", "operations_audit_events", ["strategy_id"]
    )
    op.create_index(
        "ix_operations_audit_events_content_item_id", "operations_audit_events", ["content_item_id"]
    )
    op.create_index(
        "ix_operations_audit_events_event_type", "operations_audit_events", ["event_type"]
    )
    op.create_index(
        "ix_operations_audit_events_created_at", "operations_audit_events", ["created_at"]
    )


def downgrade() -> None:
    op.drop_table("operations_audit_events")
    op.drop_table("approval_requests")
    op.drop_table("content_dependencies")
    op.drop_table("content_items")
    op.drop_table("content_campaigns")
    op.drop_table("content_series")
    op.drop_table("content_strategy_pillars")
    op.drop_table("content_strategies")
