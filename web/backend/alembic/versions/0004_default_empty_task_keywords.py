"""Default Web task keywords to an empty list."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004_default_empty_task_keywords"
down_revision = "0003_remove_serverchan_notifications"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.alter_column(
            "task_keywords_json",
            existing_type=sa.Text(),
            existing_nullable=False,
            server_default="[]",
        )


def downgrade() -> None:
    with op.batch_alter_table("settings") as batch_op:
        batch_op.alter_column(
            "task_keywords_json",
            existing_type=sa.Text(),
            existing_nullable=False,
            server_default='["晚归"]',
        )
