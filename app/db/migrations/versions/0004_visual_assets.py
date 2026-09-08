"""Add Phase 4 visual assets, visual plans and thumbnails."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004_visual_assets"
down_revision: str | None = "0003_video_projects"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    json_type = postgresql.JSONB() if op.get_bind().dialect.name == "postgresql" else sa.JSON()
    op.add_column(
        "projects",
        sa.Column("allow_external_vision", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "projects",
        sa.Column("brand_preset", json_type, nullable=False, server_default=sa.text("'{}'")),
    )
    op.execute(
        sa.DDL(
            "UPDATE projects SET brand_preset = "
            '\'{"name":"Koderevox",'
            '"visual_style":"dark clean technical minimal premium",'
            '"thumbnail_preset":"tech_dark",'
            '"subtitle_preset":"tech","logo_path":null,'
            '"safe_margin_top":140,"safe_margin_bottom":360}\' '
            "WHERE name = 'Koderevox'"
        )
    )
    op.add_column(
        "video_projects",
        sa.Column("visual_plan", json_type, nullable=False, server_default=sa.text("'{}'")),
    )
    op.add_column("video_projects", sa.Column("selected_thumbnail_id", sa.Uuid()))
    op.create_index(
        "ix_video_projects_selected_thumbnail_id",
        "video_projects",
        ["selected_thumbnail_id"],
    )

    op.create_table(
        "visual_assets",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column(
            "source_item_id",
            sa.Uuid(),
            sa.ForeignKey("source_items.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "parent_asset_id",
            sa.Uuid(),
            sa.ForeignKey("visual_assets.id", ondelete="SET NULL"),
        ),
        sa.Column(
            "type",
            sa.Enum(
                "image",
                "screenshot",
                "screen_recording",
                "video",
                "code",
                "logo",
                "diagram",
                "document_page",
                "generated_graphic",
                name="assettype",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "processing",
                "ready",
                "failed",
                "archived",
                name="assetstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("original_path", sa.String(1024), nullable=False),
        sa.Column("processed_path", sa.String(1024)),
        sa.Column("thumbnail_path", sa.String(1024)),
        sa.Column("filename", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(255), nullable=False),
        sa.Column("file_size", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("duration", sa.Float()),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("tags", json_type, nullable=False),
        sa.Column("extracted_text", sa.Text()),
        sa.Column("analysis", json_type, nullable=False),
        sa.Column("favorite", sa.Boolean(), nullable=False),
        sa.Column("license_type", sa.String(100)),
        sa.Column("source", sa.String(1024)),
        sa.Column("author", sa.String(255)),
        sa.Column("attribution_required", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("project_id", "source_item_id", "parent_asset_id", "favorite"):
        op.create_index(f"ix_visual_assets_{column}", "visual_assets", [column])

    op.create_table(
        "asset_usages",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "asset_id",
            sa.Uuid(),
            sa.ForeignKey("visual_assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "video_project_id",
            sa.Uuid(),
            sa.ForeignKey("video_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("start", sa.Float(), nullable=False),
        sa.Column("end", sa.Float(), nullable=False),
        sa.Column("usage_type", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "asset_id",
            "video_project_id",
            "start",
            "end",
            "usage_type",
            name="uq_asset_usage_timeline",
        ),
    )
    op.create_index("ix_asset_usages_asset_id", "asset_usages", ["asset_id"])
    op.create_index("ix_asset_usages_video_project_id", "asset_usages", ["video_project_id"])

    op.create_table(
        "thumbnail_projects",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("project_id", sa.Uuid(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column(
            "video_project_id",
            sa.Uuid(),
            sa.ForeignKey("video_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.Enum(
                "draft",
                "rendering",
                "rendered",
                "selected",
                "failed",
                name="thumbnailstatus",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("concept", json_type, nullable=False),
        sa.Column("render_settings", json_type, nullable=False),
        sa.Column("output_path", sa.String(1024)),
        sa.Column("metrics", json_type, nullable=False),
        sa.Column("render_fingerprint", sa.String(64)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_thumbnail_projects_project_id", "thumbnail_projects", ["project_id"])
    op.create_index(
        "ix_thumbnail_projects_video_project_id", "thumbnail_projects", ["video_project_id"]
    )
    op.create_index(
        "ix_thumbnail_projects_render_fingerprint",
        "thumbnail_projects",
        ["render_fingerprint"],
    )


def downgrade() -> None:
    op.drop_table("thumbnail_projects")
    op.drop_table("asset_usages")
    op.drop_table("visual_assets")
    op.drop_index("ix_video_projects_selected_thumbnail_id", table_name="video_projects")
    op.drop_column("video_projects", "selected_thumbnail_id")
    op.drop_column("video_projects", "visual_plan")
    op.drop_column("projects", "brand_preset")
    op.drop_column("projects", "allow_external_vision")
