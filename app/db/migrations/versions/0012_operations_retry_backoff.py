"""Persist bounded retry scheduling for operational content items."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_operations_retry_backoff"
down_revision: str | None = "0011_persistent_progress"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("content_items", sa.Column("next_retry_at", sa.DateTime(timezone=True)))
    op.create_index("ix_content_items_next_retry_at", "content_items", ["next_retry_at"])


def downgrade() -> None:
    op.drop_index("ix_content_items_next_retry_at", table_name="content_items")
    op.drop_column("content_items", "next_retry_at")
