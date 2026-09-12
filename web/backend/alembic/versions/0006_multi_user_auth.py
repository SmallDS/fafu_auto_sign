"""Add multi-user authentication and scheduling tables."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0006_multi_user_auth"
down_revision = "0005_amap_map_settings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("setup_state", sa.String(32), nullable=False, server_default="uninitialized"),
        sa.Column("public_base_url", sa.Text(), nullable=True),
        sa.Column("menu_name", sa.String(32), nullable=False, server_default="签到管理"),
        sa.Column("wechat_app_id", sa.Text(), nullable=True),
        sa.Column("wechat_app_secret", sa.Text(), nullable=True),
        sa.Column("wechat_template_id", sa.Text(), nullable=True),
        sa.Column("wechat_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("amap_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("amap_js_key", sa.Text(), nullable=True),
        sa.Column("amap_security_js_code", sa.Text(), nullable=True),
        sa.Column("log_level", sa.String(16), nullable=False, server_default="INFO"),
        sa.Column("menu_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute(
        """
        INSERT INTO system_settings (
            id, setup_state, menu_name, wechat_app_id, wechat_app_secret,
            wechat_template_id, wechat_enabled, amap_enabled, amap_js_key,
            amap_security_js_code, log_level, created_at, updated_at
        )
        SELECT 1, 'system_configured', '签到管理', wechat_test_app_id,
               wechat_test_app_secret, wechat_test_template_id,
               CASE WHEN wechat_test_app_id IS NOT NULL THEN 1 ELSE 0 END,
               amap_enabled, amap_js_key, amap_security_js_code, log_level,
               CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        FROM settings WHERE id = 1
        """
    )
    op.execute(
        """
        INSERT INTO system_settings (
            id, setup_state, menu_name, wechat_enabled, amap_enabled,
            log_level, created_at, updated_at
        )
        SELECT 1, 'uninitialized', '签到管理', 1, 0, 'INFO',
               CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        WHERE NOT EXISTS (SELECT 1 FROM system_settings WHERE id = 1)
        """
    )

    op.create_table(
        "users",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("openid", sa.Text(), nullable=False, unique=True),
        sa.Column("unionid", sa.Text(), nullable=True),
        sa.Column("nickname", sa.String(64), nullable=True),
        sa.Column("avatar_storage_name", sa.String(100), nullable=True),
        sa.Column("role", sa.String(16), nullable=False, server_default="user"),
        sa.Column("status", sa.String(24), nullable=False, server_default="profile_pending"),
        sa.Column("rejection_reason", sa.Text(), nullable=True),
        sa.Column("push_available", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("profile_authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_openid", "users", ["openid"], unique=True)
    op.create_index("ix_users_unionid", "users", ["unionid"])
    op.create_index("ix_users_role", "users", ["role"])
    op.create_index("ix_users_status", "users", ["status"])

    op.create_table(
        "login_pairings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("claim_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("verifier_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exchanged_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_login_pairings_user_id", "login_pairings", ["user_id"])

    op.create_table(
        "user_sessions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("csrf_token", sa.String(64), nullable=False),
        sa.Column("device_type", sa.String(16), nullable=False),
        sa.Column("user_agent", sa.String(255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_user_sessions_user_id", "user_sessions", ["user_id"])
    op.create_index("ix_user_sessions_token_hash", "user_sessions", ["token_hash"], unique=True)
    op.create_index("ix_user_sessions_expires_at", "user_sessions", ["expires_at"])

    op.create_table(
        "oauth_states",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("state_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("purpose", sa.String(32), nullable=False),
        sa.Column("expected_openid", sa.Text(), nullable=True),
        sa.Column("pairing_id", sa.String(36), sa.ForeignKey("login_pairings.id", ondelete="CASCADE")),
        sa.Column("next_path", sa.Text(), nullable=False, server_default="/dashboard"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_oauth_states_state_hash", "oauth_states", ["state_hash"], unique=True)
    op.create_index("ix_oauth_states_expires_at", "oauth_states", ["expires_at"])

    op.create_table(
        "sign_jobs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="20"),
        sa.Column("task_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
    )
    op.create_index("ix_sign_jobs_user_id", "sign_jobs", ["user_id"])
    op.create_index("ix_sign_jobs_kind", "sign_jobs", ["kind"])
    op.create_index("ix_sign_jobs_status", "sign_jobs", ["status"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("actor_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("target_user_id", sa.String(36), nullable=True),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("result", sa.String(16), nullable=False, server_default="success"),
        sa.Column("detail", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_actor_user_id", "audit_logs", ["actor_user_id"])
    op.create_index("ix_audit_logs_target_user_id", "audit_logs", ["target_user_id"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])

    op.execute("DELETE FROM run_history")
    op.execute("DELETE FROM images")
    op.execute("DELETE FROM settings")
    with op.batch_alter_table("settings") as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(36), nullable=True))
        batch_op.add_column(sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("notification_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))
        batch_op.create_foreign_key(
            "fk_settings_user_id_users", "users", ["user_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_index("ix_settings_user_id", ["user_id"], unique=True)
    with op.batch_alter_table("images") as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(36), nullable=True))
        batch_op.create_foreign_key(
            "fk_images_user_id_users", "users", ["user_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_index("ix_images_user_id", ["user_id"])
    with op.batch_alter_table("run_history") as batch_op:
        batch_op.add_column(sa.Column("user_id", sa.String(36), nullable=True))
        batch_op.create_foreign_key(
            "fk_run_history_user_id_users", "users", ["user_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_index("ix_run_history_user_id", ["user_id"])


def downgrade() -> None:
    with op.batch_alter_table("run_history") as batch_op:
        batch_op.drop_index("ix_run_history_user_id")
        batch_op.drop_constraint("fk_run_history_user_id_users", type_="foreignkey")
        batch_op.drop_column("user_id")
    with op.batch_alter_table("images") as batch_op:
        batch_op.drop_index("ix_images_user_id")
        batch_op.drop_constraint("fk_images_user_id_users", type_="foreignkey")
        batch_op.drop_column("user_id")
    with op.batch_alter_table("settings") as batch_op:
        batch_op.drop_index("ix_settings_user_id")
        batch_op.drop_constraint("fk_settings_user_id_users", type_="foreignkey")
        batch_op.drop_column("notification_enabled")
        batch_op.drop_column("next_run_at")
        batch_op.drop_column("user_id")
    op.drop_table("audit_logs")
    op.drop_table("sign_jobs")
    op.drop_table("oauth_states")
    op.drop_table("user_sessions")
    op.drop_table("login_pairings")
    op.drop_table("users")
    op.drop_table("system_settings")
