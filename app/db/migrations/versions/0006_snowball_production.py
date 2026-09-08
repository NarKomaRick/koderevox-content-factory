"""Add the Phase 4.5 snowball production workspace."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_snowball_production"
down_revision: str | None = "0005_publishing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _enum(name: str, *values: str) -> sa.Enum:
    return sa.Enum(*values, name=name, native_enum=False)


def upgrade() -> None:
    json_type = postgresql.JSONB() if op.get_bind().dialect.name == "postgresql" else sa.JSON()
    op.create_table(
        "production_projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column(
            "initial_source_item_id",
            sa.Uuid(),
            sa.ForeignKey("source_items.id", ondelete="SET NULL"),
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("working_title", sa.String(500), nullable=False),
        sa.Column(
            "status",
            _enum(
                "productionstatus",
                "idea",
                "research",
                "scripting",
                "ready_for_voiceover",
                "voiceover_processing",
                "voiceover_ready",
                "assembling",
                "rough_cut",
                "review",
                "approved",
                "archived",
            ),
            nullable=False,
        ),
        sa.Column("target_format", sa.String(64), nullable=False),
        sa.Column("target_duration", sa.Float()),
        sa.Column("current_script_version_id", sa.Uuid()),
        sa.Column("approved_script_version_id", sa.Uuid()),
        sa.Column("primary_voiceover_id", sa.Uuid()),
        sa.Column(
            "active_video_project_id",
            sa.Uuid(),
            sa.ForeignKey("video_projects.id", ondelete="SET NULL"),
        ),
        sa.Column("active_timeline_revision_id", sa.Uuid()),
        sa.Column("production_context", json_type, nullable=False),
        sa.Column("persistent_instructions", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in (
        "project_id",
        "user_id",
        "initial_source_item_id",
        "current_script_version_id",
        "approved_script_version_id",
        "primary_voiceover_id",
        "active_video_project_id",
        "active_timeline_revision_id",
    ):
        op.create_index(f"ix_production_projects_{column}", "production_projects", [column])

    op.create_table(
        "production_materials",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "production_project_id",
            sa.Uuid(),
            sa.ForeignKey("production_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_item_id", sa.Uuid(), sa.ForeignKey("source_items.id", ondelete="SET NULL")
        ),
        sa.Column("asset_id", sa.Uuid(), sa.ForeignKey("visual_assets.id", ondelete="SET NULL")),
        sa.Column("roles", json_type, nullable=False),
        sa.Column("user_instruction", sa.Text()),
        sa.Column("is_user_locked", sa.Boolean(), nullable=False),
        sa.Column("is_used", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "production_project_id", "source_item_id", name="uq_production_material_source"
        ),
        sa.UniqueConstraint(
            "production_project_id", "asset_id", name="uq_production_material_asset"
        ),
    )
    for column in ("production_project_id", "source_item_id", "asset_id", "is_used"):
        op.create_index(f"ix_production_materials_{column}", "production_materials", [column])

    op.create_table(
        "production_facts",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "production_project_id",
            sa.Uuid(),
            sa.ForeignKey("production_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column(
            "source_item_id", sa.Uuid(), sa.ForeignKey("source_items.id", ondelete="SET NULL")
        ),
        sa.Column("source_url", sa.String(2048)),
        sa.Column(
            "status",
            _enum("productionfactstatus", "proposed", "verified", "user_confirmed", "rejected"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("production_project_id", "source_item_id"):
        op.create_index(f"ix_production_facts_{column}", "production_facts", [column])

    op.create_table(
        "script_versions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "production_project_id",
            sa.Uuid(),
            sa.ForeignKey("production_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("structured_sections", json_type, nullable=False),
        sa.Column(
            "source", _enum("scriptsource", "ai", "user", "ai_edited", "import"), nullable=False
        ),
        sa.Column("user_instruction", sa.Text()),
        sa.Column("diff", json_type, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint(
            "production_project_id", "version_number", name="uq_script_project_version"
        ),
    )
    op.create_index(
        "ix_script_versions_production_project_id", "script_versions", ["production_project_id"]
    )

    op.create_table(
        "voiceover_tracks",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "production_project_id",
            sa.Uuid(),
            sa.ForeignKey("production_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "source_item_id",
            sa.Uuid(),
            sa.ForeignKey("source_items.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("original_path", sa.String(1024), nullable=False),
        sa.Column("processed_path", sa.String(1024), nullable=False),
        sa.Column("duration", sa.Float(), nullable=False),
        sa.Column("language", sa.String(16)),
        sa.Column("transcript", sa.Text(), nullable=False),
        sa.Column("segments", json_type, nullable=False),
        sa.Column("words", json_type, nullable=False),
        sa.Column(
            "script_version_id",
            sa.Uuid(),
            sa.ForeignKey("script_versions.id", ondelete="SET NULL"),
        ),
        sa.Column("alignment", json_type, nullable=False),
        sa.Column("alignment_score", sa.Float()),
        sa.Column(
            "status",
            _enum("voiceoverstatus", "processing", "ready", "failed", "replaced"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("production_project_id", "source_item_id", "script_version_id"):
        op.create_index(f"ix_voiceover_tracks_{column}", "voiceover_tracks", [column])

    op.create_table(
        "timeline_revisions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "production_project_id",
            sa.Uuid(),
            sa.ForeignKey("production_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("timeline_json", json_type, nullable=False),
        sa.Column("user_instruction", sa.Text()),
        sa.Column("change_summary", sa.Text()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "production_project_id", "revision_number", name="uq_timeline_project_revision"
        ),
    )
    op.create_index(
        "ix_timeline_revisions_production_project_id",
        "timeline_revisions",
        ["production_project_id"],
    )

    op.create_table(
        "runtime_settings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("scope", sa.String(32), nullable=False),
        sa.Column("scope_id", sa.Uuid()),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("value", json_type, nullable=False),
        sa.Column("updated_by_user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("scope", "scope_id", "key", name="uq_runtime_setting_scope_key"),
    )
    op.create_index("ix_runtime_settings_key", "runtime_settings", ["key"])

    op.create_table(
        "encrypted_secrets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "owner_user_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("owner_user_id", "name", name="uq_encrypted_secret_owner_name"),
    )
    op.create_index("ix_encrypted_secrets_owner_user_id", "encrypted_secrets", ["owner_user_id"])


def downgrade() -> None:
    for table in (
        "encrypted_secrets",
        "runtime_settings",
        "timeline_revisions",
        "voiceover_tracks",
        "script_versions",
        "production_facts",
        "production_materials",
        "production_projects",
    ):
        op.drop_table(table)
