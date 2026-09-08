"""Add Phase 5 publishing queue, accounts, credentials and audit state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005_publishing"
down_revision: str | None = "0004_visual_assets"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False)


def upgrade() -> None:
    json_type = postgresql.JSONB() if op.get_bind().dialect.name == "postgresql" else sa.JSON()
    op.add_column(
        "projects",
        sa.Column("timezone", sa.String(64), nullable=False, server_default="Europe/Moscow"),
    )

    op.create_table(
        "publish_packages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column(
            "content_draft_id",
            sa.Uuid(),
            sa.ForeignKey("content_drafts.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "video_project_id",
            sa.Uuid(),
            sa.ForeignKey("video_projects.id", ondelete="SET NULL"),
            unique=True,
        ),
        sa.Column(
            "thumbnail_project_id",
            sa.Uuid(),
            sa.ForeignKey("thumbnail_projects.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "status",
            _enum(
                "publishpackagestatus",
                "draft",
                "ready",
                "partially_published",
                "published",
                "failed",
                "archived",
            ),
            nullable=False,
        ),
        sa.Column("master_video_path", sa.String(1024)),
        sa.Column("master_thumbnail_path", sa.String(1024)),
        sa.Column("base_title", sa.String(500), nullable=False),
        sa.Column("base_caption", sa.Text(), nullable=False),
        sa.Column("base_description", sa.Text(), nullable=False),
        sa.Column("metadata", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        "project_id",
        "content_draft_id",
        "video_project_id",
        "thumbnail_project_id",
    ):
        op.create_index(f"ix_publish_packages_{column}", "publish_packages", [column])

    op.create_table(
        "platform_variants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "publish_package_id",
            sa.Uuid(),
            sa.ForeignKey("publish_packages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "platform",
            _enum("publishingplatform", "telegram", "youtube", "tiktok"),
            nullable=False,
        ),
        sa.Column("video_path", sa.String(1024)),
        sa.Column("thumbnail_path", sa.String(1024)),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("caption", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("hashtags", json_type, nullable=False),
        sa.Column("settings", json_type, nullable=False),
        sa.Column("media_profile", json_type, nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("publish_package_id", "platform", name="uq_variant_package_platform"),
    )
    op.create_index(
        "ix_platform_variants_publish_package_id",
        "platform_variants",
        ["publish_package_id"],
    )
    op.create_index("ix_platform_variants_content_hash", "platform_variants", ["content_hash"])

    op.create_table(
        "platform_accounts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column(
            "platform",
            _enum("platformaccountplatform", "telegram", "youtube", "tiktok"),
            nullable=False,
        ),
        sa.Column("display_name", sa.String(255), nullable=False),
        sa.Column("external_account_id", sa.String(512)),
        sa.Column("username", sa.String(255)),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("capabilities", json_type, nullable=False),
        sa.Column("settings", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "project_id", "platform", "display_name", name="uq_account_project_platform_name"
        ),
    )
    op.create_index("ix_platform_accounts_project_id", "platform_accounts", ["project_id"])
    op.create_index("ix_platform_accounts_is_active", "platform_accounts", ["is_active"])

    op.create_table(
        "encrypted_credentials",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "platform_account_id",
            sa.Uuid(),
            sa.ForeignKey("platform_accounts.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("encrypted_payload", sa.LargeBinary(), nullable=False),
        sa.Column("key_version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_encrypted_credentials_platform_account_id",
        "encrypted_credentials",
        ["platform_account_id"],
    )

    op.create_table(
        "publications",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "publish_package_id",
            sa.Uuid(),
            sa.ForeignKey("publish_packages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "platform_variant_id",
            sa.Uuid(),
            sa.ForeignKey("platform_variants.id"),
            nullable=False,
        ),
        sa.Column(
            "platform_account_id",
            sa.Uuid(),
            sa.ForeignKey("platform_accounts.id"),
            nullable=False,
        ),
        sa.Column(
            "platform",
            _enum("publicationplatform", "telegram", "youtube", "tiktok"),
            nullable=False,
        ),
        sa.Column(
            "status",
            _enum(
                "publicationstatus",
                "draft",
                "scheduled",
                "queued",
                "publishing",
                "processing",
                "published",
                "published_with_warning",
                "retry_wait",
                "failed",
                "cancelled",
            ),
            nullable=False,
        ),
        sa.Column("scheduled_at", sa.DateTime(timezone=True)),
        sa.Column("next_retry_at", sa.DateTime(timezone=True)),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("claimed_at", sa.DateTime(timezone=True)),
        sa.Column("remote_id", sa.String(512)),
        sa.Column("remote_url", sa.String(2048)),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("last_error_code", sa.String(100)),
        sa.Column("last_error_message", sa.Text()),
        sa.Column("metadata", json_type, nullable=False),
        sa.Column("variant_snapshot", json_type, nullable=False),
        sa.Column("variant_hash", sa.String(64), nullable=False),
        sa.Column("media_hash", sa.String(64)),
        sa.Column("idempotency_key", sa.String(255), unique=True),
        sa.Column("task_id", sa.String(255)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        "publish_package_id",
        "platform_variant_id",
        "platform_account_id",
        "scheduled_at",
        "next_retry_at",
        "published_at",
        "remote_id",
        "media_hash",
        "idempotency_key",
    ):
        op.create_index(f"ix_publications_{column}", "publications", [column])

    op.create_table(
        "publication_attempts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "publication_id",
            sa.Uuid(),
            sa.ForeignKey("publications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True)),
        sa.Column(
            "status",
            _enum(
                "publicationattemptstatus",
                "started",
                "processing",
                "succeeded",
                "retry_scheduled",
                "failed",
            ),
            nullable=False,
        ),
        sa.Column("provider_error_code", sa.String(255)),
        sa.Column("sanitized_error", sa.Text()),
        sa.Column("provider_request_id", sa.String(512)),
        sa.Column("media_hash", sa.String(64)),
        sa.Column("metadata", json_type, nullable=False),
        sa.UniqueConstraint("publication_id", "attempt_number", name="uq_attempt_number"),
    )
    op.create_index(
        "ix_publication_attempts_publication_id", "publication_attempts", ["publication_id"]
    )

    op.create_table(
        "publication_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "publication_id",
            sa.Uuid(),
            sa.ForeignKey("publications.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "event_type",
            _enum(
                "publicationeventtype",
                "created",
                "scheduled",
                "claimed",
                "upload_started",
                "remote_accepted",
                "processing",
                "published",
                "failed",
                "retried",
                "cancelled",
            ),
            nullable=False,
        ),
        sa.Column("details", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_publication_events_publication_id", "publication_events", ["publication_id"]
    )

    op.create_table(
        "oauth_states",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("state_hash", sa.String(64), nullable=False, unique=True),
        sa.Column(
            "platform",
            _enum("oauthstateplatform", "telegram", "youtube", "tiktok"),
            nullable=False,
        ),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column(
            "platform_account_id",
            sa.Uuid(),
            sa.ForeignKey("platform_accounts.id", ondelete="CASCADE"),
        ),
        sa.Column("redirect_after", sa.String(1024)),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("state_hash", "project_id", "platform_account_id", "expires_at"):
        op.create_index(f"ix_oauth_states_{column}", "oauth_states", [column])

    op.create_table(
        "webhook_receipts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "platform",
            _enum("webhookplatform", "telegram", "youtube", "tiktok"),
            nullable=False,
        ),
        sa.Column("external_event_id", sa.String(512), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("platform", "external_event_id", name="uq_webhook_external_event"),
    )


def downgrade() -> None:
    op.drop_table("webhook_receipts")
    op.drop_table("oauth_states")
    op.drop_table("publication_events")
    op.drop_table("publication_attempts")
    op.drop_table("publications")
    op.drop_table("encrypted_credentials")
    op.drop_table("platform_accounts")
    op.drop_table("platform_variants")
    op.drop_table("publish_packages")
    op.drop_column("projects", "timezone")
