"""Add WeChat test-account notification settings."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0002_wechat_test_account_notifications"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(
            sa.Column("wechat_test_enabled", sa.Boolean(), nullable=False, server_default=sa.false())
        )
        batch_op.add_column(sa.Column("wechat_test_app_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("wechat_test_app_secret", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("wechat_test_template_id", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("wechat_test_openid", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_column("wechat_test_openid")
        batch_op.drop_column("wechat_test_template_id")
        batch_op.drop_column("wechat_test_app_secret")
        batch_op.drop_column("wechat_test_app_id")
        batch_op.drop_column("wechat_test_enabled")