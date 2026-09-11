"""Add optional AMap display settings."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0005_amap_map_settings"
down_revision = "0004_default_empty_task_keywords"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "settings",
        sa.Column("amap_enabled", sa.Boolean(), nullable=False, server_default=sa.text("0")),
    )
    op.add_column("settings", sa.Column("amap_js_key", sa.Text(), nullable=True))
    op.add_column("settings", sa.Column("amap_security_js_code", sa.Text(), nullable=True))
    op.add_column(
        "settings",
        sa.Column(
            "amap_source_coordinate_system",
            sa.String(length=16),
            nullable=False,
            server_default="gcj02",
        ),
    )


def downgrade() -> None:
    op.drop_column("settings", "amap_source_coordinate_system")
    op.drop_column("settings", "amap_security_js_code")
    op.drop_column("settings", "amap_js_key")
    op.drop_column("settings", "amap_enabled")
