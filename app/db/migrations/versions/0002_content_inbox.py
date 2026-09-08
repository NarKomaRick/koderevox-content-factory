"""Add Phase 2 content inbox and processing fields."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_content_inbox"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("source_items", sa.Column("telegram_unique_file_id", sa.String(512)))
    op.add_column("source_items", sa.Column("telegram_chat_id", sa.BigInteger()))
    op.add_column("source_items", sa.Column("telegram_message_id", sa.BigInteger()))
    op.add_column("source_items", sa.Column("telegram_update_id", sa.BigInteger()))
    op.add_column("source_items", sa.Column("processed_file_path", sa.String(1024)))
    op.add_column("source_items", sa.Column("mime_type", sa.String(255)))
    op.add_column("source_items", sa.Column("file_size", sa.BigInteger()))
    op.add_column("source_items", sa.Column("original_filename", sa.String(512)))
    op.add_column("source_items", sa.Column("duration_seconds", sa.Float()))
    op.add_column(
        "source_items",
        sa.Column("processing_stage", sa.String(32), nullable=False, server_default="received"),
    )
    op.add_column("source_items", sa.Column("processing_error", sa.Text()))
    op.add_column("source_items", sa.Column("transcript_language", sa.String(16)))
    op.add_column(
        "source_items",
        sa.Column("transcript_segments", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.add_column("source_items", sa.Column("extracted_text", sa.Text()))
    op.add_column("source_items", sa.Column("summary", sa.Text()))
    op.add_column("source_items", sa.Column("topic", sa.String(500)))
    op.add_column("source_items", sa.Column("content_potential_score", sa.Integer()))
    op.add_column(
        "source_items",
        sa.Column("content_analysis", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column(
        "source_items",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.add_column("source_items", sa.Column("completed_at", sa.DateTime(timezone=True)))
    with op.batch_alter_table("source_items") as batch_op:
        batch_op.alter_column(
            "type", existing_type=sa.String(8), type_=sa.String(16), existing_nullable=False
        )
        batch_op.create_unique_constraint("uq_source_telegram_update_id", ["telegram_update_id"])
        batch_op.create_unique_constraint(
            "uq_source_telegram_message", ["telegram_chat_id", "telegram_message_id"]
        )
    op.create_index(
        "ix_source_items_telegram_unique_file_id", "source_items", ["telegram_unique_file_id"]
    )
    op.create_index("ix_source_items_topic", "source_items", ["topic"])
    op.create_index(
        "ix_source_items_content_potential_score", "source_items", ["content_potential_score"]
    )

    op.create_table(
        "source_notes",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "source_item_id",
            sa.Uuid(),
            sa.ForeignKey("source_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("text", sa.Text()),
        sa.Column("transcript", sa.Text()),
        sa.Column("telegram_file_id", sa.String(512)),
        sa.Column("telegram_unique_file_id", sa.String(512)),
        sa.Column("telegram_update_id", sa.BigInteger(), unique=True),
        sa.Column("local_file_path", sa.String(1024)),
        sa.Column("mime_type", sa.String(255)),
        sa.Column("file_size", sa.BigInteger()),
        sa.Column("metadata", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_source_notes_source_item_id", "source_notes", ["source_item_id"])
    op.create_index("ix_source_notes_user_id", "source_notes", ["user_id"])


def downgrade() -> None:
    op.drop_table("source_notes")
    op.drop_index("ix_source_items_content_potential_score", table_name="source_items")
    op.drop_index("ix_source_items_topic", table_name="source_items")
    op.drop_index("ix_source_items_telegram_unique_file_id", table_name="source_items")
    with op.batch_alter_table("source_items") as batch_op:
        batch_op.drop_constraint("uq_source_telegram_message", type_="unique")
        batch_op.drop_constraint("uq_source_telegram_update_id", type_="unique")
        batch_op.alter_column(
            "type", existing_type=sa.String(16), type_=sa.String(8), existing_nullable=False
        )
    for column in (
        "completed_at",
        "updated_at",
        "content_analysis",
        "content_potential_score",
        "topic",
        "summary",
        "extracted_text",
        "transcript_segments",
        "transcript_language",
        "processing_error",
        "processing_stage",
        "duration_seconds",
        "original_filename",
        "file_size",
        "mime_type",
        "processed_file_path",
        "telegram_update_id",
        "telegram_message_id",
        "telegram_chat_id",
        "telegram_unique_file_id",
    ):
        op.drop_column("source_items", column)
