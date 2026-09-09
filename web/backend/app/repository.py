"""Transactional repository helpers."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import redact_sensitive_payload, redact_sensitive_text
from app.models import AppMeta, Image, RunHistory, Settings, utcnow
from app.paths import LATEST_DIR, LIBRARY_DIR
from app.schemas import ImageRead, RunRead, SettingsRead, SettingsUpdate

if TYPE_CHECKING:
    from fafu_auto_sign.executor import RunSummary


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
        wechat_test_enabled=settings.wechat_test_enabled,
        wechat_test_app_id=settings.wechat_test_app_id,
        wechat_test_template_id=settings.wechat_test_template_id,
        has_wechat_test_app_secret=bool(settings.wechat_test_app_secret),
        wechat_test_app_secret_masked=mask_secret(settings.wechat_test_app_secret),
        has_wechat_test_openid=bool(settings.wechat_test_openid),
        wechat_test_openid_masked=mask_secret(settings.wechat_test_openid),
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

    if payload.clear_wechat_test_app_secret:
        settings.wechat_test_app_secret = None
        settings.wechat_test_enabled = False
    elif "wechat_test_app_secret" in fields_set and payload.wechat_test_app_secret:
        settings.wechat_test_app_secret = payload.wechat_test_app_secret
    if payload.clear_wechat_test_openid:
        settings.wechat_test_openid = None
        settings.wechat_test_enabled = False
    elif "wechat_test_openid" in fields_set and payload.wechat_test_openid:
        settings.wechat_test_openid = payload.wechat_test_openid

    for name in (
        "jitter",
        "heartbeat_interval",
        "log_level",
        "wechat_test_enabled",
        "wechat_test_app_id",
        "wechat_test_template_id",
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

    if settings.wechat_test_enabled and not all((
        settings.wechat_test_app_id,
        settings.wechat_test_app_secret,
        settings.wechat_test_template_id,
        settings.wechat_test_openid,
    )):
        raise ValueError("启用微信测试号前必须完整配置 AppID、AppSecret、模板 ID 和 OpenID")
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


def save_run_summary(session: Session, summary: "RunSummary") -> RunHistory:
    """Persist one executor summary for worker and direct manual submissions."""
    task_results = redact_sensitive_payload(summary.to_dict().get("task_results", []))
    text = summary.error or {
        "no_task": "未发现待签到任务",
        "success": "签到成功",
        "partial": "部分任务处理失败",
        "failed": "签到失败",
        "fatal": "发生致命错误，调度已暂停",
    }.get(summary.status, summary.status)
    row = RunHistory(
        trigger=summary.trigger,
        config_version=summary.config_version,
        started_at=summary.started_at,
        finished_at=summary.finished_at,
        status=summary.status,
        discovered_count=summary.discovered_count,
        success_count=summary.success_count,
        failure_count=summary.failure_count,
        summary=redact_sensitive_text(text, "执行结果不可用") or "执行结果不可用",
        task_details_json=json.dumps(task_results, ensure_ascii=False),
        error=redact_sensitive_text(summary.error),
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return row
