"""Administrator APIs for users, secrets, sessions, system settings and audit."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth import AdminUser
from app.auth_routes import avatar_url
from app.database import get_db
from app.errors import api_error
from app.models import AuditLog, Image, RunHistory, SignJob, User, UserSession, utcnow
from app.paths import user_root
from app.repository import (
    audit,
    configuration_state,
    image_path,
    image_to_read,
    get_or_create_settings,
    get_or_create_system_settings,
    run_to_read,
    settings_to_read,
    system_settings_to_read,
    update_settings,
    update_system_settings,
)
from app.schemas import (
    AuditLogRead,
    AuditPage,
    ImagePage,
    RunPage,
    SessionRead,
    SettingsRead,
    SettingsUpdate,
    SystemSettingsRead,
    SystemSettingsUpdate,
    UserAdminRead,
    UserAdminUpdate,
    UserPage,
    WorkerActionResponse,
)
from app.wechat import WeChatError, sync_menu
from fafu_auto_sign.services.wechat_test_account_service import (
    WeChatTestAccountError,
    WeChatTestAccountService,
)

router = APIRouter(prefix="/api/admin")
DbSession = Annotated[Session, Depends(get_db)]


def ensure_last_admin_safe(
    session: Session, user: User, *, changing_role: bool = False
) -> None:
    if user.role != "admin" or user.status != "active":
        return
    count = session.scalar(
        select(func.count(User.id)).where(User.role == "admin", User.status == "active")
    ) or 0
    if count <= 1:
        action = "降级" if changing_role else "禁用或删除"
        raise api_error(409, "LAST_ADMIN_PROTECTED", f"不能{action}最后一个有效管理员")


def admin_user_read(session: Session, user: User) -> UserAdminRead:
    settings = get_or_create_settings(session, user.id)
    configured, _ = configuration_state(session, settings)
    return UserAdminRead(
        id=user.id,
        openid=user.openid,
        unionid=user.unionid,
        nickname=user.nickname,
        avatar_url=avatar_url(user),
        role=user.role,
        status=user.status,
        rejection_reason=user.rejection_reason,
        configured=configured,
        worker_enabled=settings.worker_enabled,
        last_login_at=user.last_login_at,
        created_at=user.created_at,
    )


def notify_approval(session: Session, target: User) -> None:
    system = get_or_create_system_settings(session)
    if not (
        target.push_available
        and system.wechat_enabled
        and system.wechat_app_id
        and system.wechat_app_secret
        and system.wechat_template_id
    ):
        return
    try:
        WeChatTestAccountService(
            system.wechat_app_id,
            system.wechat_app_secret,
            system.wechat_template_id,
            target.openid,
        ).send("账号审核通过", "您的 FAFU 签到账号已通过审核")
    except WeChatTestAccountError:
        target.push_available = False
        session.commit()


@router.get("/users", response_model=UserPage)
def list_users(
    admin: AdminUser,
    session: DbSession,
    status: str | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> UserPage:
    query = select(User)
    count_query = select(func.count(User.id))
    if status:
        query = query.where(User.status == status)
        count_query = count_query.where(User.status == status)
    total = session.scalar(count_query) or 0
    rows = session.scalars(
        query.order_by(User.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return UserPage(
        items=[admin_user_read(session, row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/users/{user_id}", response_model=UserAdminRead)
def get_user(user_id: str, admin: AdminUser, session: DbSession) -> UserAdminRead:
    target = session.get(User, user_id)
    if target is None:
        raise api_error(404, "USER_NOT_FOUND", "用户不存在")
    return admin_user_read(session, target)


@router.put("/users/{user_id}", response_model=UserAdminRead)
def update_user(
    user_id: str, payload: UserAdminUpdate, admin: AdminUser, session: DbSession
) -> UserAdminRead:
    target = session.get(User, user_id)
    if target is None:
        raise api_error(404, "USER_NOT_FOUND", "用户不存在")
    if payload.role == "user" and target.role == "admin":
        ensure_last_admin_safe(session, target, changing_role=True)
    if payload.status in {"disabled", "rejected"}:
        ensure_last_admin_safe(session, target)
    if payload.role is not None:
        target.role = payload.role
    if payload.status is not None:
        target.status = payload.status
        target.rejection_reason = (
            payload.rejection_reason.strip()
            if payload.status == "rejected" and payload.rejection_reason
            else None
        )
        if payload.status in {"disabled", "rejected"}:
            get_or_create_settings(session, target.id).worker_enabled = False
    audit(
        session,
        admin.id,
        "user.update",
        target_user_id=target.id,
        detail=f"role={target.role}, status={target.status}",
        commit=False,
    )
    session.commit()
    if target.status == "active":
        notify_approval(session, target)
    return admin_user_read(session, target)


@router.get("/users/{user_id}/settings", response_model=SettingsRead)
def get_user_settings(
    user_id: str, admin: AdminUser, session: DbSession
) -> SettingsRead:
    if session.get(User, user_id) is None:
        raise api_error(404, "USER_NOT_FOUND", "用户不存在")
    return settings_to_read(session, get_or_create_settings(session, user_id))


@router.put("/users/{user_id}/settings", response_model=SettingsRead)
def put_user_settings(
    user_id: str,
    payload: SettingsUpdate,
    admin: AdminUser,
    session: DbSession,
) -> SettingsRead:
    if session.get(User, user_id) is None:
        raise api_error(404, "USER_NOT_FOUND", "用户不存在")
    settings = update_settings(session, payload, user_id)
    audit(session, admin.id, "user.settings.update", target_user_id=user_id)
    return settings_to_read(session, settings)


@router.post("/users/{user_id}/token/reveal")
def reveal_user_token(
    user_id: str, admin: AdminUser, session: DbSession
) -> dict[str, str | None]:
    if session.get(User, user_id) is None:
        raise api_error(404, "USER_NOT_FOUND", "用户不存在")
    token = get_or_create_settings(session, user_id).user_token
    audit(session, admin.id, "user.token.reveal", target_user_id=user_id)
    return {"user_token": token}


@router.get("/users/{user_id}/sessions", response_model=list[SessionRead])
def list_user_sessions(
    user_id: str, admin: AdminUser, session: DbSession
) -> list[SessionRead]:
    if session.get(User, user_id) is None:
        raise api_error(404, "USER_NOT_FOUND", "用户不存在")
    rows = session.scalars(
        select(UserSession)
        .where(UserSession.user_id == user_id, UserSession.revoked_at.is_(None))
        .order_by(UserSession.last_seen_at.desc())
    ).all()
    return [
        SessionRead(
            id=row.id,
            device_type=row.device_type,
            user_agent=row.user_agent,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            expires_at=row.expires_at,
            current=False,
        )
        for row in rows
    ]


@router.get("/users/{user_id}/images", response_model=ImagePage)
def list_user_images(
    user_id: str,
    admin: AdminUser,
    session: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> ImagePage:
    if session.get(User, user_id) is None:
        raise api_error(404, "USER_NOT_FOUND", "用户不存在")
    total = session.scalar(
        select(func.count(Image.id)).where(Image.user_id == user_id)
    ) or 0
    rows = session.scalars(
        select(Image)
        .where(Image.user_id == user_id)
        .order_by(Image.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return ImagePage(
        items=[image_to_read(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/users/{user_id}/images/{image_id}", response_class=FileResponse)
def get_user_image(
    user_id: str, image_id: str, admin: AdminUser, session: DbSession
) -> FileResponse:
    row = session.scalar(
        select(Image).where(Image.id == image_id, Image.user_id == user_id)
    )
    if row is None:
        raise api_error(404, "IMAGE_NOT_FOUND", "图片不存在")
    path = image_path(row)
    if not path.is_file():
        raise api_error(404, "IMAGE_FILE_MISSING", "图片文件不存在")
    return FileResponse(path, media_type=row.mime_type)


@router.get("/users/{user_id}/runs", response_model=RunPage)
def list_user_runs(
    user_id: str,
    admin: AdminUser,
    session: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
) -> RunPage:
    if session.get(User, user_id) is None:
        raise api_error(404, "USER_NOT_FOUND", "用户不存在")
    total = session.scalar(
        select(func.count(RunHistory.id)).where(RunHistory.user_id == user_id)
    ) or 0
    rows = session.scalars(
        select(RunHistory)
        .where(RunHistory.user_id == user_id)
        .order_by(RunHistory.started_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return RunPage(
        items=[run_to_read(row) for row in rows],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/users/{user_id}/notifications/test", response_model=WorkerActionResponse)
def test_user_notification(
    user_id: str, admin: AdminUser, session: DbSession
) -> WorkerActionResponse:
    target = session.get(User, user_id)
    system = get_or_create_system_settings(session)
    if target is None:
        raise api_error(404, "USER_NOT_FOUND", "用户不存在")
    if not all(
        (
            target.openid,
            system.wechat_enabled,
            system.wechat_app_id,
            system.wechat_app_secret,
            system.wechat_template_id,
        )
    ):
        raise api_error(409, "WECHAT_NOT_CONFIGURED", "微信测试号通知配置不完整")
    try:
        accepted = WeChatTestAccountService(
            system.wechat_app_id,
            system.wechat_app_secret,
            system.wechat_template_id,
            target.openid,
        ).send("FAFU 签到助手测试", "管理员已向您的账号发送测试消息")
    except WeChatTestAccountError as exc:
        target.push_available = False
        audit(
            session,
            admin.id,
            "user.notification.test",
            target_user_id=user_id,
            result="failed",
            detail="测试消息发送失败",
            commit=False,
        )
        session.commit()
        raise api_error(502, "WECHAT_NOTIFICATION_FAILED", "测试消息发送失败") from exc
    audit(
        session,
        admin.id,
        "user.notification.test",
        target_user_id=user_id,
        commit=False,
    )
    session.commit()
    return WorkerActionResponse(
        state="idle", message="测试消息已提交" if accepted else "测试消息未提交"
    )


@router.post("/users/{user_id}/sessions/revoke", status_code=204)
def revoke_user_sessions(user_id: str, admin: AdminUser, session: DbSession) -> None:
    if session.get(User, user_id) is None:
        raise api_error(404, "USER_NOT_FOUND", "用户不存在")
    now = utcnow()
    for row in session.scalars(
        select(UserSession).where(
            UserSession.user_id == user_id, UserSession.revoked_at.is_(None)
        )
    ):
        row.revoked_at = now
    audit(
        session,
        admin.id,
        "user.sessions.revoke",
        target_user_id=user_id,
        commit=False,
    )
    session.commit()


@router.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: str, admin: AdminUser, session: DbSession) -> None:
    target = session.get(User, user_id)
    if target is None:
        raise api_error(404, "USER_NOT_FOUND", "用户不存在")
    ensure_last_admin_safe(session, target)
    running = session.scalar(
        select(SignJob).where(
            SignJob.user_id == user_id, SignJob.status == "running"
        )
    )
    if running is not None:
        raise api_error(409, "USER_JOB_RUNNING", "该用户正在执行签到，请稍后再删除")
    session.query(SignJob).filter(
        SignJob.user_id == user_id, SignJob.status == "queued"
    ).update({"status": "cancelled"})
    session.delete(target)
    audit(session, admin.id, "user.delete", target_user_id=user_id, commit=False)
    session.commit()
    try:
        shutil.rmtree(user_root(user_id), ignore_errors=False)
    except FileNotFoundError:
        pass
    except OSError:
        audit(
            session,
            admin.id,
            "user.files.cleanup",
            target_user_id=user_id,
            result="failed",
            detail="用户数据文件需要重试清理",
        )


@router.get("/system", response_model=SystemSettingsRead)
def get_system(admin: AdminUser, session: DbSession) -> SystemSettingsRead:
    return system_settings_to_read(get_or_create_system_settings(session))


@router.put("/system", response_model=SystemSettingsRead)
def put_system(
    payload: SystemSettingsUpdate, admin: AdminUser, session: DbSession
) -> SystemSettingsRead:
    try:
        row = update_system_settings(session, payload)
    except ValueError as exc:
        session.rollback()
        raise api_error(422, "VALIDATION_ERROR", str(exc)) from exc
    audit(session, admin.id, "system.settings.update")
    return system_settings_to_read(row)


@router.post("/system/secret/reveal")
def reveal_system_secret(
    admin: AdminUser, session: DbSession
) -> dict[str, str | None]:
    row = get_or_create_system_settings(session)
    audit(session, admin.id, "system.secret.reveal")
    return {
        "wechat_app_secret": row.wechat_app_secret,
        "amap_security_js_code": row.amap_security_js_code,
    }


@router.post("/system/menu/sync", response_model=WorkerActionResponse)
def synchronize_menu(
    admin: AdminUser, session: DbSession
) -> WorkerActionResponse:
    row = get_or_create_system_settings(session)
    if not (
        row.wechat_app_id
        and row.wechat_app_secret
        and row.public_base_url
        and row.menu_name
    ):
        raise api_error(409, "WECHAT_NOT_CONFIGURED", "微信测试号或公网地址配置不完整")
    try:
        sync_menu(
            row.wechat_app_id,
            row.wechat_app_secret,
            row.public_base_url,
            row.menu_name,
        )
    except WeChatError as exc:
        audit(session, admin.id, "system.menu.sync", result="failed", detail=str(exc))
        raise api_error(502, "WECHAT_MENU_FAILED", str(exc)) from exc
    row.menu_synced_at = utcnow()
    audit(session, admin.id, "system.menu.sync", commit=False)
    session.commit()
    return WorkerActionResponse(state="idle", message="公众号菜单已同步")


@router.get("/audit", response_model=AuditPage)
def list_audit(
    admin: AdminUser,
    session: DbSession,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=30, ge=1, le=100),
    target_user_id: str | None = None,
) -> AuditPage:
    query = select(AuditLog)
    count_query = select(func.count(AuditLog.id))
    if target_user_id:
        query = query.where(AuditLog.target_user_id == target_user_id)
        count_query = count_query.where(AuditLog.target_user_id == target_user_id)
    total = session.scalar(count_query) or 0
    rows = session.scalars(
        query.order_by(AuditLog.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return AuditPage(
        items=[
            AuditLogRead(
                id=row.id,
                actor_user_id=row.actor_user_id,
                target_user_id=row.target_user_id,
                action=row.action,
                result=row.result,
                detail=row.detail,
                created_at=row.created_at,
            )
            for row in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )