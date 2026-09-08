"""Initial Web persistence schema."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_token", sa.Text(), nullable=True),
        sa.Column("jitter", sa.Float(), nullable=False, server_default="0.00005"),
        sa.Column("heartbeat_interval", sa.Integer(), nullable=False, server_default="900"),
        sa.Column("log_level", sa.String(16), nullable=False, server_default="INFO"),
        sa.Column("notification_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("serverchan_key", sa.Text(), nullable=True),
        sa.Column("task_keywords_json", sa.Text(), nullable=False, server_default='["晚归"]'),
        sa.Column("image_mode", sa.String(16), nullable=False, server_default="single"),
        sa.Column("current_image_id", sa.String(36), nullable=True),
        sa.Column("worker_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("config_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "images",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("original_name", sa.Text(), nullable=False),
        sa.Column("storage_name", sa.String(80), nullable=False, unique=True),
        sa.Column("mime_type", sa.String(64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_images_purpose", "images", ["purpose"])
    op.create_index("ix_images_sha256", "images", ["sha256"])
    op.create_index("ix_images_created_at", "images", ["created_at"])
    op.create_table(
        "run_history",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("trigger", sa.String(16), nullable=False),
        sa.Column("config_version", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("discovered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("task_details_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_run_history_trigger", "run_history", ["trigger"])
    op.create_index("ix_run_history_started_at", "run_history", ["started_at"])
    op.create_index("ix_run_history_status", "run_history", ["status"])
    op.create_table(
        "app_meta",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("app_meta")
    op.drop_index("ix_run_history_status", table_name="run_history")
    op.drop_index("ix_run_history_started_at", table_name="run_history")
    op.drop_index("ix_run_history_trigger", table_name="run_history")
    op.drop_table("run_history")
    op.drop_index("ix_images_created_at", table_name="images")
    op.drop_index("ix_images_sha256", table_name="images")
    op.drop_index("ix_images_purpose", table_name="images")
    op.drop_table("images")
    op.drop_table("settings")