"""Add per-user FAFU authentication mode and renewable WeLink sessions."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0007_fafu_auth_sessions"
down_revision = "0006_multi_user_auth"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch:
        batch.add_column(
            sa.Column(
                "fafu_auth_mode", sa.String(16), nullable=False,
                server_default="manual",
            )
        )
    op.create_table(
        "fafu_auth_sessions",
        sa.Column(
            "user_id", sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True,
        ),
        sa.Column("username", sa.Text(), nullable=False),
        sa.Column("password", sa.Text(), nullable=False),
        sa.Column("device_id", sa.Text(), nullable=False),
        sa.Column("we_link_token", sa.Text(), nullable=True),
        sa.Column("refresh_token", sa.Text(), nullable=True),
        sa.Column("refresh_fail", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("next_refresh_after", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("reconnect_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("resume_worker_after_reconnect", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("fafu_auth_sessions")
    with op.batch_alter_table("settings") as batch:
        batch.drop_column("fafu_auth_mode")
