"""SQLAlchemy persistence models."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def utcnow() -> datetime:
    """Return an aware UTC timestamp."""
    return datetime.now(timezone.utc)


class Settings(Base):
    __tablename__ = "settings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    user_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    jitter: Mapped[float] = mapped_column(Float, nullable=False, default=0.00005)
    heartbeat_interval: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    log_level: Mapped[str] = mapped_column(String(16), nullable=False, default="INFO")
    wechat_test_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    wechat_test_app_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    wechat_test_app_secret: Mapped[str | None] = mapped_column(Text, nullable=True)
    wechat_test_template_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    wechat_test_openid: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_keywords_json: Mapped[str] = mapped_column(Text, nullable=False, default='["晚归"]')
    image_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="single")
    current_image_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    worker_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    config_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


class Image(Base):
    __tablename__ = "images"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
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
