"""SQLAlchemy persistence models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(timezone.utc)


class SystemSettings(Base):
    __tablename__ = "system_settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    setup_state: Mapped[str] = mapped_column(String(32), nullable=False, default="uninitialized")
    public_base_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    menu_name: Mapped[str] = mapped_column(String(32), nullable=False, default="签到管理")
    wechat_app_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    wechat_app_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    wechat_template_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    wechat_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    amap_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    amap_js_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    amap_security_js_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    log_level: Mapped[str] = mapped_column(String(16), nullable=False, default="INFO")
    menu_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    openid: Mapped[str] = mapped_column(Text, nullable=False, unique=True, index=True)
    unionid: Mapped[str | None] = mapped_column(Text, nullable=True, index=True)
    nickname: Mapped[str | None] = mapped_column(String(64), nullable=True)
    avatar_storage_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="user", index=True)
    status: Mapped[str] = mapped_column(
        String(24), nullable=False, default="profile_pending", index=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    push_available: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    profile_authorized_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Settings(Base):
    """Per-user FAFU settings. The legacy table name is retained for migration safety."""

    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, unique=True, index=True
    )
    user_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    jitter: Mapped[float] = mapped_column(Float, nullable=False, default=0.00005)
    heartbeat_interval: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    log_level: Mapped[str] = mapped_column(String(16), nullable=False, default="INFO")
    amap_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    amap_js_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    amap_security_js_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    amap_source_coordinate_system: Mapped[str] = mapped_column(
        String(16), nullable=False, default="gcj02"
    )
    wechat_test_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notification_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    wechat_test_app_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    wechat_test_app_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    wechat_test_template_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    wechat_test_openid: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_keywords_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    image_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="single")
    current_image_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    worker_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class UserSession(Base):
    __tablename__ = "user_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    csrf_token: Mapped[str] = mapped_column(String(64), nullable=False)
    device_type: Mapped[str] = mapped_column(String(16), nullable=False)
    user_agent: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class OAuthState(Base):
    __tablename__ = "oauth_states"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    purpose: Mapped[str] = mapped_column(String(32), nullable=False)
    expected_openid: Mapped[str | None] = mapped_column(Text, nullable=True)
    pairing_id: Mapped[str | None] = mapped_column(
        ForeignKey("login_pairings.id", ondelete="CASCADE"), nullable=True
    )
    next_path: Mapped[str] = mapped_column(Text, nullable=False, default="/dashboard")
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class LoginPairing(Base):
    __tablename__ = "login_pairings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    claim_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    verifier_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="pending")
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exchanged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SignJob(Base):
    __tablename__ = "sign_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False, index=True)
    priority: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    task_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="queued", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    target_user_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    result: Mapped[str] = mapped_column(String(16), nullable=False, default="success")
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Image(Base):
    __tablename__ = "images"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    purpose: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    original_name: Mapped[str] = mapped_column(Text, nullable=False)
    storage_name: Mapped[str] = mapped_column(String(80), nullable=False, unique=True)
    mime_type: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, index=True
    )


class RunHistory(Base):
    __tablename__ = "run_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    trigger: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    finished_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    discovered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    success_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    failure_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    task_details_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class AppMeta(Base):
    __tablename__ = "app_meta"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )
