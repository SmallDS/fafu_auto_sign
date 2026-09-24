"""Session authentication and authorization helpers."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.errors import api_error
from app.models import User, UserSession, utcnow

SESSION_COOKIE = "fafu_session"
PAIRING_COOKIE = "fafu_pairing_verifier"
SESSION_DAYS = 30
MAX_USER_SESSIONS = 10


def as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def hash_token(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def random_token() -> str:
    return secrets.token_urlsafe(32)


def cookie_secure(request: Request | None) -> bool:
    """Keep HTTPS cookies Secure while allowing an explicit HTTP LAN entry."""
    if request is None:
        return True
    forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",", 1)[0].strip().lower()
    return request.url.scheme == "https" or forwarded_proto == "https"


def set_session_cookie(response: Response, raw_token: str, *, request: Request | None = None) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        raw_token,
        max_age=SESSION_DAYS * 86400,
        httponly=True,
        secure=cookie_secure(request),
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response, *, request: Request | None = None) -> None:
    response.delete_cookie(
        SESSION_COOKIE, path="/", secure=cookie_secure(request), samesite="lax"
    )


def create_user_session(
    session: Session,
    user: User,
    *,
    device_type: str,
    user_agent: str,
) -> tuple[UserSession, str]:
    now = utcnow()
    raw_token = random_token()
    row = UserSession(
        id=str(uuid.uuid4()),
        user_id=user.id,
        token_hash=hash_token(raw_token),
        csrf_token=random_token(),
        device_type=device_type,
        user_agent=user_agent[:255],
        created_at=now,
        last_seen_at=now,
        expires_at=now + timedelta(days=SESSION_DAYS),
    )
    session.add(row)
    session.flush()
    active = session.scalars(
        select(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
        .order_by(UserSession.last_seen_at.desc())
    ).all()
    for stale in active[MAX_USER_SESSIONS:]:
        stale.revoked_at = now
    user.last_login_at = now
    session.commit()
    session.refresh(row)
    return row, raw_token


def resolve_session(
    request: Request,
    session: Session,
    *,
    allow_inactive: bool = True,
) -> tuple[User, UserSession]:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        raise api_error(401, "AUTH_REQUIRED", "请先登录")
    row = session.scalar(
        select(UserSession).where(UserSession.token_hash == hash_token(raw))
    )
    now = datetime.now(timezone.utc)
    if row is None or row.revoked_at is not None or as_utc(row.expires_at) <= now:
        raise api_error(401, "SESSION_EXPIRED", "登录已过期，请重新登录")
    user = session.get(User, row.user_id)
    if user is None:
        raise api_error(401, "SESSION_EXPIRED", "登录已失效")
    if not allow_inactive:
        if user.status == "pending":
            raise api_error(403, "ACCOUNT_PENDING", "账号正在等待管理员审核")
        if user.status == "rejected":
            raise api_error(403, "ACCOUNT_REJECTED", "账号申请已被驳回")
        if user.status == "disabled":
            raise api_error(403, "ACCOUNT_DISABLED", "账号已被禁用")
        if user.status == "profile_pending":
            raise api_error(403, "PROFILE_REQUIRED", "请先完善昵称与头像")
    if now - as_utc(row.last_seen_at) >= timedelta(minutes=5):
        row.last_seen_at = now
        row.expires_at = now + timedelta(days=SESSION_DAYS)
        session.commit()
    request.state.auth_session = row
    return user, row


def current_user(
    request: Request, session: Annotated[Session, Depends(get_db)]
) -> User:
    return resolve_session(request, session)[0]


def active_user(
    request: Request, session: Annotated[Session, Depends(get_db)]
) -> User:
    user, _ = resolve_session(request, session, allow_inactive=False)
    if user.status != "active":
        raise api_error(403, "FORBIDDEN", "当前账号不可访问此功能")
    return user


def admin_user(
    request: Request, session: Annotated[Session, Depends(get_db)]
) -> User:
    user = active_user(request, session)
    if user.role != "admin":
        raise api_error(403, "FORBIDDEN", "需要管理员权限")
    return user


def check_csrf(request: Request, session: Session) -> None:
    if request.method in {"GET", "HEAD", "OPTIONS"}:
        return
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return
    row = session.scalar(
        select(UserSession).where(UserSession.token_hash == hash_token(raw))
    )
    provided = request.headers.get("X-CSRF-Token", "")
    if row is None or not hmac.compare_digest(row.csrf_token, provided):
        raise api_error(403, "CSRF_INVALID", "安全校验失败，请刷新页面后重试")


CurrentUser = Annotated[User, Depends(current_user)]
ActiveUser = Annotated[User, Depends(active_user)]
AdminUser = Annotated[User, Depends(admin_user)]
