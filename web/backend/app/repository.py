"""Transactional repository helpers."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import AppMeta, Image, RunHistory, Settings, utcnow
from app.paths import LATEST_DIR, LIBRARY_DIR
from app.schemas import ImageRead, RunRead, SettingsRead, SettingsUpdate


def mask_secret(value: str | None) -> str | None:
    """Mask a secret while leaving a small recognition suffix."""
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:3]}{'*' * min(12, len(value) - 6)}{value[-3:]}"


def get_or_create_settings(session: Session) -> Settings:
    settings = session.get(Settings, 1)
    if settings is None:
        settings = Settings(id=1)
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings


def settings_to_read(session: Session, settings: Settings) -> SettingsRead:
    configured, _ = configuration_state(session, settings)
    return SettingsRead(
        configured=configured,
        version=settings.config_version,
        has_user_token=bool(settings.user_token),
        user_token_masked=mask_secret(settings.user_token),
        jitter=settings.jitter,
        heartbeat_interval=settings.heartbeat_interval,
        log_level=settings.log_level,
        notification_enabled=settings.notification_enabled,
        has_serverchan_key=bool(settings.serverchan_key),
        serverchan_key_masked=mask_secret(settings.serverchan_key),
        task_keywords=json.loads(settings.task_keywords_json),
        image_mode=settings.image_mode,  # type: ignore[arg-type]
        selected_image_id=settings.current_image_id,
        worker_enabled=settings.worker_enabled,
    )


def update_settings(session: Session, payload: SettingsUpdate) -> Settings:
    settings = get_or_create_settings(session)
    fields_set = payload.model_fields_set
    values = payload.model_dump(exclude_unset=True)

    if payload.clear_user_token:
        settings.user_token = None
    elif "user_token" in fields_set and payload.user_token:
        settings.user_token = payload.user_token

    if payload.clear_serverchan_key:
        settings.serverchan_key = None
    elif "serverchan_key" in fields_set and payload.serverchan_key:
        settings.serverchan_key = payload.serverchan_key

    for name in (
        "jitter",
        "heartbeat_interval",
        "log_level",
        "notification_enabled",
        "image_mode",
        "worker_enabled",
    ):
        if name in fields_set and values.get(name) is not None:
            setattr(settings, name, values[name])
    if "task_keywords" in fields_set and payload.task_keywords is not None:
        settings.task_keywords_json = json.dumps(payload.task_keywords, ensure_ascii=False)
    if "selected_image_id" in fields_set:
        if (
            payload.selected_image_id is not None
            and session.get(Image, payload.selected_image_id) is None
        ):
            raise ValueError("选择的图片不存在")
        settings.current_image_id = payload.selected_image_id

    if settings.notification_enabled and not settings.serverchan_key:
        raise ValueError("启用通知前必须配置 SendKey")
    if settings.image_mode == "single" and settings.current_image_id:
        image = session.get(Image, settings.current_image_id)
        if image is None or image.purpose != "library":
            raise ValueError("单图模式必须选择图库中的图片")

    settings.config_version += 1
    settings.updated_at = utcnow()
    session.commit()
    session.refresh(settings)
    return settings


def image_path(image: Image) -> Path:
    root = LIBRARY_DIR if image.purpose == "library" else LATEST_DIR
    path = (root / image.storage_name).resolve()
    if root.resolve() not in path.parents:
        raise ValueError("图片路径越界")
    return path


def configuration_state(
    session: Session, settings: Settings | None = None
) -> tuple[bool, list[str]]:
    settings = settings or get_or_create_settings(session)
    missing: list[str] = []
    if not settings.user_token:
        missing.append("user_token")
    if settings.image_mode == "single":
        image = session.get(Image, settings.current_image_id) if settings.current_image_id else None
        if image is None or not image_path(image).is_file():
            missing.append("current_image")
    else:
        purpose = "library" if settings.image_mode == "library" else "latest"
        images = session.scalars(select(Image).where(Image.purpose == purpose)).all()
        if not any(image_path(item).is_file() for item in images):
            missing.append(f"{purpose}_images")
    return (not missing, missing)


def image_to_read(image: Image) -> ImageRead:
    return ImageRead(
        id=image.id,
        category=image.purpose,  # type: ignore[arg-type]
        original_name=image.original_name,
        mime_type=image.mime_type,
        size=image.size,
        sha256=image.sha256,
        created_at=image.created_at,
    )


def run_to_read(run: RunHistory) -> RunRead:
    try:
        details = json.loads(run.task_details_json)
    except json.JSONDecodeError:
        details = []
    return RunRead(
        id=run.id,
        trigger=run.trigger,  # type: ignore[arg-type]
        config_version=run.config_version,
        started_at=run.started_at,
        finished_at=run.finished_at,
        result=run.status,  # type: ignore[arg-type]
        task_count=run.discovered_count,
        success_count=run.success_count,
        failure_count=run.failure_count,
        summary=run.summary,
        details=details,
    )


def latest_run(session: Session) -> RunHistory | None:
    return session.scalar(select(RunHistory).order_by(RunHistory.started_at.desc()).limit(1))


def seven_day_stats(session: Session) -> dict[str, int]:
    since = datetime.now(timezone.utc) - timedelta(days=7)
    rows = session.execute(
        select(RunHistory.status, func.count(RunHistory.id))
        .where(RunHistory.started_at >= since)
        .group_by(RunHistory.status)
    ).all()
    stats = {name: 0 for name in ("no_task", "success", "partial", "failed", "fatal")}
    for status, count in rows:
        stats[str(status)] = int(count)
    stats["total"] = sum(stats.values())
    return stats


def set_meta(session: Session, key: str, value: str) -> None:
    row = session.get(AppMeta, key)
    if row is None:
        session.add(AppMeta(key=key, value=value))
    else:
        row.value = value
        row.updated_at = utcnow()
    session.commit()


def get_meta(session: Session, key: str) -> str | None:
    row = session.get(AppMeta, key)
    return row.value if row else None
