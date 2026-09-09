"""Remove legacy ServerChan notification settings."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003_remove_serverchan_notifications"
down_revision = "0002_wechat_test_account_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("serverchan_key")
        batch_op.drop_column("notification_enabled")


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(
            sa.Column(
                "notification_enabled",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            )
        )
        batch_op.add_column(sa.Column("serverchan_key", sa.Text(), nullable=True))
