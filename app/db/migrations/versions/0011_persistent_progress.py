"""Add durable cross-pipeline progress snapshots and throttled events."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_persistent_progress"
down_revision: str | None = "0010_content_operations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = sa.JSON()
    now = sa.text("CURRENT_TIMESTAMP")
    op.create_table(
        "job_progress",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("job_type", sa.String(32), nullable=False),
        sa.Column("job_id", sa.String(255), nullable=False),
        sa.Column(
            "content_item_id", sa.Uuid(), sa.ForeignKey("content_items.id", ondelete="SET NULL")
        ),
        sa.Column(
            "producer_run_id", sa.Uuid(), sa.ForeignKey("producer_runs.id", ondelete="SET NULL")
        ),
        sa.Column(
            "director_run_id", sa.Uuid(), sa.ForeignKey("director_runs.id", ondelete="SET NULL")
        ),
        sa.Column(
            "production_project_id",
            sa.Uuid(),
            sa.ForeignKey("production_projects.id", ondelete="SET NULL"),
        ),
        sa.Column("state", sa.String(24), nullable=False, server_default="created"),
        sa.Column("stage", sa.String(64), nullable=False, server_default="created"),
        sa.Column("stage_label", sa.String(255), nullable=False, server_default=""),
        sa.Column("step_index", sa.Integer()),
        sa.Column("step_total", sa.Integer()),
        sa.Column("stage_progress", sa.Float()),
        sa.Column("message", sa.String(2000), nullable=False, server_default=""),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column("estimated_remaining_seconds", sa.Float()),
        sa.Column("eta_confidence", sa.String(16), nullable=False, server_default="none"),
        sa.Column("error_code", sa.String(128)),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source_kind", sa.String(16), nullable=False, server_default="production"),
        sa.Column("telegram_chat_id", sa.BigInteger()),
        sa.Column("telegram_message_id", sa.BigInteger()),
        sa.Column("metadata_json", json_type, nullable=False, server_default=sa.text("'{}'")),
        sa.UniqueConstraint("job_type", "job_id", name="uq_job_progress_job"),
    )
    for name, column in (
        ("job_progress_job_type", "job_type"),
        ("job_progress_job_id", "job_id"),
        ("job_progress_content_item_id", "content_item_id"),
        ("job_progress_updated_at", "updated_at"),
        ("job_progress_state", "state"),
    ):
        op.create_index(name, "job_progress", [column])
    op.create_table(
        "progress_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "progress_id",
            sa.Uuid(),
            sa.ForeignKey("job_progress.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("event_type", sa.String(24), nullable=False),
        sa.Column("stage", sa.String(64), nullable=False),
        sa.Column("stage_progress", sa.Float()),
        sa.Column("message", sa.String(2000), nullable=False, server_default=""),
        sa.Column("source_kind", sa.String(16), nullable=False, server_default="production"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=now),
        sa.Column("duration_seconds", sa.Float()),
    )
    for name, column in (
        ("progress_events_progress_id", "progress_id"),
        ("progress_events_event_type", "event_type"),
        ("progress_events_stage", "stage"),
        ("progress_events_source_kind", "source_kind"),
        ("progress_events_occurred_at", "occurred_at"),
    ):
        op.create_index(name, "progress_events", [column])


def downgrade() -> None:
    for name in (
        "progress_events_occurred_at",
        "progress_events_source_kind",
        "progress_events_stage",
        "progress_events_event_type",
        "progress_events_progress_id",
    ):
        op.drop_index(name, table_name="progress_events")
    op.drop_table("progress_events")
    for name in (
        "job_progress_state",
        "job_progress_updated_at",
        "job_progress_content_item_id",
        "job_progress_job_id",
        "job_progress_job_type",
    ):
        op.drop_index(name, table_name="job_progress")
    op.drop_table("job_progress")
