"""Transactional repository helpers with mandatory per-user isolation."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import redact_sensitive_payload, redact_sensitive_text
from app.models import (
    AuditLog, AppMeta, FafuAuthSession, Image, RunHistory, Settings,
    SystemSettings, utcnow,
)
from app.paths import LIBRARY_DIR, LATEST_DIR, user_image_dir
from app.schemas import (
    ImageRead,
    RunRead,
    SettingsRead,
    SettingsUpdate,
    SystemSettingsRead,
    SystemSettingsUpdate,
)

if TYPE_CHECKING:
    from fafu_auto_sign.executor import RunSummary


def mask_secret(value: str | None) -> str | None:
    if not value:
        return None
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:3]}{'*' * min(12, len(value) - 6)}{value[-3:]}"


def get_or_create_system_settings(session: Session) -> SystemSettings:
    row = session.get(SystemSettings, 1)
    if row is None:
        row = SystemSettings(id=1)
        session.add(row)
        session.commit()
        session.refresh(row)
    return row


def get_or_create_settings(session: Session, user_id: str | None = None) -> Settings:
    query = select(Settings)
    query = query.where(Settings.user_id == user_id)
    settings = session.scalar(query.limit(1))
    if settings is None:
        settings = Settings(user_id=user_id)
        session.add(settings)
        session.commit()
        session.refresh(settings)
    return settings


def settings_to_read(session: Session, settings: Settings) -> SettingsRead:
    configured, _ = configuration_state(session, settings)
    auth = session.get(FafuAuthSession, settings.user_id) if settings.user_id else None
    if settings.fafu_auth_mode == "auto" and auth is not None:
        now = utcnow()
        retry_at = auth.next_refresh_after
        if retry_at is not None and retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=timezone.utc)
        auth_status = (
            "reconnect_required" if auth.reconnect_required
            else "refresh_backoff" if retry_at is not None and retry_at > now
            else "connected"
        )
        auth_mode = "auto"
    elif settings.fafu_auth_mode == "auto":
        auth_status = "reconnect_required"
        auth_mode = "auto"
    else:
        auth_status = "manual" if settings.user_token else "unconfigured"
        auth_mode = "manual" if settings.user_token else None
    return SettingsRead(
        configured=configured,
        version=settings.config_version,
        has_user_token=bool(settings.user_token),
        user_token_masked=mask_secret(settings.user_token),
        fafu_auth_mode=auth_mode,
        fafu_auth_status=auth_status,
        fafu_username_masked=mask_secret(auth.username) if auth_mode == "auto" and auth else None,
        fafu_last_refresh_at=auth.last_refresh_at if auth_mode == "auto" and auth else None,
        fafu_last_error=redact_sensitive_text(auth.last_error) if auth_mode == "auto" and auth else None,
        jitter=settings.jitter,
        heartbeat_interval=settings.heartbeat_interval,
        task_keywords=json.loads(settings.task_keywords_json),
        image_mode=settings.image_mode,
        selected_image_id=settings.current_image_id,
        worker_enabled=settings.worker_enabled,
        notification_enabled=settings.notification_enabled,
    )


def system_settings_to_read(settings: SystemSettings) -> SystemSettingsRead:
    return SystemSettingsRead(
        setup_state=settings.setup_state,
        public_base_url=settings.public_base_url,
        menu_name=settings.menu_name,
        wechat_app_id=settings.wechat_app_id,
        wechat_template_id=settings.wechat_template_id,
        wechat_enabled=settings.wechat_enabled,
        has_wechat_app_secret=bool(settings.wechat_app_secret),
        wechat_app_secret_masked=mask_secret(settings.wechat_app_secret),
        amap_enabled=settings.amap_enabled,
        amap_js_key=settings.amap_js_key,
        has_amap_security_js_code=bool(settings.amap_security_js_code),
        amap_security_js_code_masked=mask_secret(settings.amap_security_js_code),
        log_level=settings.log_level,
        menu_synced_at=settings.menu_synced_at,
    )


def update_settings(
    session: Session, payload: SettingsUpdate, user_id: str | None = None
) -> Settings:
    settings = get_or_create_settings(session, user_id)
    fields_set = payload.model_fields_set
    values = payload.model_dump(exclude_unset=True)

    if payload.clear_user_token:
        settings.user_token = None
        settings.worker_enabled = False
        settings.fafu_auth_mode = "manual"
        if user_id is not None:
            auth = session.get(FafuAuthSession, user_id)
            if auth is not None:
                session.delete(auth)
    elif "user_token" in fields_set and payload.user_token:
        settings.user_token = payload.user_token
        settings.fafu_auth_mode = "manual"
        if user_id is not None:
            auth = session.get(FafuAuthSession, user_id)
            if auth is not None:
                session.delete(auth)

    for name in (
        "jitter",
        "heartbeat_interval",
        "image_mode",
        "worker_enabled",
        "notification_enabled",
    ):
        if name in fields_set and values.get(name) is not None:
            setattr(settings, name, values[name])
    if payload.clear_user_token:
        settings.worker_enabled = False
    if "task_keywords" in fields_set and payload.task_keywords is not None:
        settings.task_keywords_json = json.dumps(payload.task_keywords, ensure_ascii=False)
    if "selected_image_id" in fields_set:
        if payload.selected_image_id is not None:
            image = session.scalar(
                select(Image).where(
                    Image.id == payload.selected_image_id,
                    Image.user_id == user_id,
                )
            )
            if image is None:
                raise ValueError("选择的图片不存在")
        settings.current_image_id = payload.selected_image_id

    if settings.image_mode == "single" and settings.current_image_id:
        image = session.scalar(
            select(Image).where(
                Image.id == settings.current_image_id,
                Image.user_id == user_id,
            )
        )
        if image is None or image.purpose != "library":
            raise ValueError("单图模式必须选择自己的图库图片")

    settings.config_version += 1
    settings.next_run_at = utcnow()
    settings.updated_at = utcnow()
    session.commit()
    session.refresh(settings)
    return settings


def update_system_settings(
    session: Session, payload: SystemSettingsUpdate
) -> SystemSettings:
    settings = get_or_create_system_settings(session)
    fields_set = payload.model_fields_set
    values = payload.model_dump(exclude_unset=True)

    if payload.clear_wechat_app_secret:
        settings.wechat_app_secret = None
        settings.wechat_enabled = False
    elif "wechat_app_secret" in fields_set and payload.wechat_app_secret:
        settings.wechat_app_secret = payload.wechat_app_secret
    if payload.clear_amap_security_js_code:
        settings.amap_security_js_code = None
        settings.amap_enabled = False
    elif "amap_security_js_code" in fields_set and payload.amap_security_js_code:
        settings.amap_security_js_code = payload.amap_security_js_code

    for name in (
        "public_base_url", "menu_name", "wechat_app_id", "wechat_template_id",
        "amap_js_key", "log_level",
    ):
        if name in fields_set and values.get(name) is not None:
            setattr(settings, name, values[name] or None)
    for name in ("wechat_enabled", "amap_enabled"):
        if name in fields_set and values.get(name) is not None:
            setattr(settings, name, values[name])

    if settings.wechat_enabled and not all(
        (settings.wechat_app_id, settings.wechat_app_secret, settings.wechat_template_id)
    ):
        raise ValueError("启用微信测试号前必须完整配置 AppID、AppSecret 和模板 ID")
    if settings.amap_enabled and not all(
        (settings.amap_js_key, settings.amap_security_js_code)
    ):
        raise ValueError("启用高德地图前必须完整配置 JS Key 和 Security JS Code")
    if settings.public_base_url and not settings.public_base_url.startswith("https://"):
        raise ValueError("公网地址必须使用 HTTPS")

    settings.updated_at = utcnow()
    session.commit()
    session.refresh(settings)
    return settings


def image_path(image: Image) -> Path:
    if image.user_id:
        root = user_image_dir(image.user_id, image.purpose)
    else:
        root = LIBRARY_DIR if image.purpose == "library" else LATEST_DIR
    path = (root / image.storage_name).resolve()
    if root.resolve() not in path.parents:
        raise ValueError("图片路径越界")
    return path


def configuration_state(
    session: Session,
    settings: Settings | None = None,
    user_id: str | None = None,
) -> tuple[bool, list[str]]:
    settings = settings or get_or_create_settings(session, user_id)
    owner = settings.user_id
    missing: list[str] = []
    if not settings.user_token:
        missing.append("user_token")
    if settings.image_mode == "single":
        image = (
            session.scalar(
                select(Image).where(
                    Image.id == settings.current_image_id,
                    Image.user_id == owner,
                )
            )
            if settings.current_image_id
            else None
        )
        if image is None or not image_path(image).is_file():
            missing.append("current_image")
    else:
        purpose = "library" if settings.image_mode == "library" else "latest"
        images = session.scalars(
            select(Image).where(Image.purpose == purpose, Image.user_id == owner)
        ).all()
        if not any(image_path(item).is_file() for item in images):
            missing.append(f"{purpose}_images")
    return (not missing, missing)


def image_to_read(image: Image) -> ImageRead:
    return ImageRead(
        id=image.id,
        category=image.purpose,
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
        trigger=run.trigger,
        config_version=run.config_version,
        started_at=run.started_at,
        finished_at=run.finished_at,
        result=run.status,
        task_count=run.discovered_count,
        success_count=run.success_count,
        failure_count=run.failure_count,
        summary=run.summary,
        details=details,
    )


def latest_run(session: Session, user_id: str | None = None) -> RunHistory | None:
    return session.scalar(
        select(RunHistory)
        .where(RunHistory.user_id == user_id)
        .order_by(RunHistory.started_at.desc())
        .limit(1)
    )


def seven_day_stats(session: Session, user_id: str | None = None) -> dict[str, int]:
    since = datetime.now(timezone.utc) - timedelta(days=7)
    rows = session.execute(
        select(RunHistory.status, func.count(RunHistory.id))
        .where(RunHistory.started_at >= since, RunHistory.user_id == user_id)
        .group_by(RunHistory.status)
    ).all()
    stats = {name: 0 for name in ("no_task", "success", "partial", "failed", "fatal")}
    for status, count in rows:
        stats[str(status)] = int(count)
    stats["total"] = sum(stats.values())
    return stats


def audit(
    session: Session,
    actor_user_id: str | None,
    action: str,
    *,
    target_user_id: str | None = None,
    result: str = "success",
    detail: str | None = None,
    commit: bool = True,
) -> AuditLog:
    row = AuditLog(
        actor_user_id=actor_user_id,
        target_user_id=target_user_id,
        action=action,
        result=result,
        detail=redact_sensitive_text(detail),
    )
    session.add(row)
    if commit:
        session.commit()
        session.refresh(row)
    return row


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


def save_run_summary(
    session: Session, summary: "RunSummary", user_id: str | None = None
) -> RunHistory:
    task_results = redact_sensitive_payload(summary.to_dict().get("task_results", []))
    text = summary.error or {
        "no_task": "未发现待签到任务",
        "success": "签到成功",
        "partial": "部分任务处理失败",
        "failed": "签到失败",
        "fatal": "发生致命错误，调度已暂停",
    }.get(summary.status, summary.status)
    row = RunHistory(
        user_id=user_id,
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
