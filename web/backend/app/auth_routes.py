"""Bootstrap, WeChat OAuth, pairing and user session routes."""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import (
    CurrentUser,
    as_utc,
    PAIRING_COOKIE,
    cookie_secure,
    clear_session_cookie,
    create_user_session,
    hash_token,
    random_token,
    resolve_session,
    set_session_cookie,
)
from app.avatar_store import MAX_AVATAR_BYTES, InvalidAvatar, avatar_path, download_wechat_avatar, store_avatar
from app.database import get_db
from app.errors import api_error
from app.models import LoginPairing, OAuthState, SystemSettings, User, UserSession, utcnow
from app.repository import get_or_create_settings, get_or_create_system_settings
from app.schemas import AuthUserRead, BootstrapStatus, BootstrapSystemRequest, PairingRead, SessionRead
from app.wechat import (
    WeChatError,
    build_oauth_url,
    exchange_oauth_code,
    fetch_oauth_profile,
    get_global_access_token,
    normalize_wechat_text,
)

router = APIRouter()
DbSession = Annotated[Session, Depends(get_db)]


def bootstrap_read(row: SystemSettings) -> BootstrapStatus:
    return BootstrapStatus(
        setup_state=row.setup_state,
        initialized=row.setup_state == "initialized",
        system_configured=row.setup_state != "uninitialized",
        admin_binding=row.setup_state == "admin_binding",
        requires_system_configuration=not all((
            row.public_base_url, row.wechat_app_id, row.wechat_app_secret,
            row.wechat_template_id,
        )),
    )


def avatar_url(user: User) -> str | None:
    return f"/api/auth/avatar/{user.id}" if user.avatar_storage_name else None


def auth_user_read(user: User, csrf: str | None = None) -> AuthUserRead:
    return AuthUserRead(
        id=user.id,
        nickname=normalize_wechat_text(user.nickname) if user.nickname else None,
        avatar_url=avatar_url(user),
        role=user.role,
        status=user.status,
        rejection_reason=user.rejection_reason,
        csrf_token=csrf,
    )


def pairing_cookie_ok(request: Request, pairing: LoginPairing) -> bool:
    raw = request.cookies.get(PAIRING_COOKIE, "")
    return bool(raw) and hash_token(raw) == pairing.verifier_hash


def pairing_read(pairing: LoginPairing, *, auth_url: str | None = None) -> PairingRead:
    return PairingRead(
        id=pairing.id,
        kind=pairing.kind,
        status=pairing.status,
        auth_url=auth_url,
        expires_at=pairing.expires_at,
    )


def safe_next(value: str) -> str:
    return value if value.startswith("/") and not value.startswith("//") else "/dashboard"


def require_oauth_settings(system: SystemSettings) -> tuple[str, str, str]:
    if not (system.wechat_app_id and system.wechat_app_secret and system.public_base_url):
        raise api_error(409, "WECHAT_NOT_CONFIGURED", "微信测试号或公网地址配置不完整")
    return system.wechat_app_id, system.wechat_app_secret, system.public_base_url


def create_oauth_state(
    session: Session,
    *,
    purpose: str,
    pairing_id: str | None,
    expected_openid: str | None,
    next_path: str,
) -> str:
    raw = random_token()
    session.add(
        OAuthState(
            id=str(uuid.uuid4()),
            state_hash=hash_token(raw),
            purpose=purpose,
            pairing_id=pairing_id,
            expected_openid=expected_openid,
            next_path=safe_next(next_path),
            expires_at=utcnow() + timedelta(minutes=10),
        )
    )
    session.commit()
    return raw


def set_pairing_from_user(pairing: LoginPairing | None, user: User) -> None:
    if pairing is None:
        return
    pairing.user_id = user.id
    pairing.scanned_at = utcnow()
    if user.status in {"pending", "profile_pending"}:
        pairing.expires_at = utcnow() + timedelta(minutes=30)
    pairing.status = {
        "active": "ready",
        "pending": "awaiting_approval",
        "profile_pending": "profile_pending",
        "rejected": "rejected",
        "disabled": "disabled",
    }.get(user.status, "expired")

@router.get("/api/bootstrap/status", response_model=BootstrapStatus)
def bootstrap_status(session: DbSession) -> BootstrapStatus:
    return bootstrap_read(get_or_create_system_settings(session))


@router.put("/api/bootstrap/system", response_model=BootstrapStatus)
def bootstrap_system(payload: BootstrapSystemRequest, session: DbSession) -> BootstrapStatus:
    system = get_or_create_system_settings(session)
    if system.setup_state != "uninitialized" and not (
        system.setup_state == "system_configured" and not system.public_base_url
    ):
        raise api_error(409, "BOOTSTRAP_CLOSED", "系统初始化配置已经锁定")
    try:
        get_global_access_token(payload.wechat_app_id, payload.wechat_app_secret)
    except WeChatError as exc:
        raise api_error(422, "WECHAT_CREDENTIALS_INVALID", str(exc)) from exc
    system.wechat_app_id = payload.wechat_app_id
    system.wechat_app_secret = payload.wechat_app_secret
    system.wechat_template_id = payload.wechat_template_id
    system.public_base_url = payload.public_base_url
    system.menu_name = payload.menu_name
    system.amap_enabled = payload.amap_enabled
    system.amap_js_key = payload.amap_js_key or None
    system.amap_security_js_code = payload.amap_security_js_code or None
    system.log_level = payload.log_level
    system.setup_state = "system_configured"
    system.updated_at = utcnow()
    session.commit()
    return bootstrap_read(system)


def create_pairing(
    session: Session, response: Response, *, kind: str, ttl_seconds: int,
    request: Request | None = None,
) -> PairingRead:
    system = get_or_create_system_settings(session)
    _, _, public_base_url = require_oauth_settings(system)
    claim = random_token()
    verifier = random_token()
    pairing = LoginPairing(
        id=str(uuid.uuid4()),
        kind=kind,
        claim_hash=hash_token(claim),
        verifier_hash=hash_token(verifier),
        status="pending",
        expires_at=utcnow() + timedelta(seconds=ttl_seconds),
    )
    if kind == "admin":
        if system.setup_state not in {"system_configured", "admin_binding"}:
            raise api_error(409, "BOOTSTRAP_CLOSED", "管理员初始化绑定不可用")
        system.setup_state = "admin_binding"
    elif system.setup_state != "initialized":
        raise api_error(409, "SYSTEM_NOT_INITIALIZED", "系统尚未完成初始化")
    session.add(pairing)
    session.commit()
    response.set_cookie(
        PAIRING_COOKIE,
        verifier,
        max_age=1800 if kind == "login" else ttl_seconds,
        httponly=True,
        secure=cookie_secure(request),
        samesite="lax",
        path="/",
    )
    auth_url = (
        f"{public_base_url}/auth/wechat/start?"
        f"pairing_id={quote(pairing.id)}&claim={quote(claim)}&next=/dashboard"
    )
    return pairing_read(pairing, auth_url=auth_url)


@router.post("/api/bootstrap/admin-pairings", response_model=PairingRead)
def create_admin_pairing(request: Request, response: Response, session: DbSession) -> PairingRead:
    return create_pairing(session, response, kind="admin", ttl_seconds=300, request=request)


@router.post("/api/auth/pairings", response_model=PairingRead)
def create_login_pairing(request: Request, response: Response, session: DbSession) -> PairingRead:
    return create_pairing(session, response, kind="login", ttl_seconds=60, request=request)


def load_pairing_for_browser(
    pairing_id: str, request: Request, session: Session
) -> LoginPairing:
    pairing = session.get(LoginPairing, pairing_id)
    if pairing is None or not pairing_cookie_ok(request, pairing):
        raise api_error(404, "PAIRING_NOT_FOUND", "登录二维码不存在")
    now = datetime.now(timezone.utc)
    if as_utc(pairing.expires_at) <= now and pairing.status in {
        "pending",
        "scanning",
        "profile_pending",
        "awaiting_approval",
        "ready",
    }:
        pairing.status = "expired"
        session.commit()
    if pairing.status == "awaiting_approval" and pairing.user_id:
        user = session.get(User, pairing.user_id)
        if user and user.status == "active":
            pairing.status = "ready"
            session.commit()
        elif user and user.status in {"rejected", "disabled"}:
            pairing.status = user.status
            session.commit()
        elif user is None:
            pairing.status = "expired"
            session.commit()
    return pairing


@router.get("/api/bootstrap/admin-pairings/{pairing_id}", response_model=PairingRead)
@router.get("/api/auth/pairings/{pairing_id}", response_model=PairingRead)
def get_pairing(pairing_id: str, request: Request, session: DbSession) -> PairingRead:
    pairing = load_pairing_for_browser(pairing_id, request, session)
    result = pairing_read(pairing)
    if pairing.user_id:
        user = session.get(User, pairing.user_id)
        result.user_status = user.status if user else None
    return result


def exchange_pairing(
    pairing_id: str,
    request: Request,
    response: Response,
    session: Session,
    expected_kind: str,
) -> AuthUserRead:
    pairing = load_pairing_for_browser(pairing_id, request, session)
    if pairing.kind != expected_kind:
        raise api_error(404, "PAIRING_NOT_FOUND", "登录二维码不存在")
    if pairing.exchanged_at is not None:
        raise api_error(409, "PAIRING_CONSUMED", "登录二维码已经使用")
    if pairing.status == "expired":
        raise api_error(410, "PAIRING_EXPIRED", "登录二维码已过期")
    if pairing.status == "rejected":
        raise api_error(403, "ACCOUNT_REJECTED", "账号审核未通过")
    if pairing.status == "disabled":
        raise api_error(403, "ACCOUNT_DISABLED", "账号已被禁用")
    if pairing.status != "ready" or not pairing.user_id:
        raise api_error(409, "PAIRING_NOT_READY", "扫码登录尚未完成")
    user = session.get(User, pairing.user_id)
    if user is None:
        raise api_error(404, "ACCOUNT_NOT_FOUND", "账号不存在")
    if user.status != "active":
        code = (
            "ACCOUNT_REJECTED"
            if user.status == "rejected"
            else "ACCOUNT_DISABLED"
            if user.status == "disabled"
            else "ACCOUNT_PENDING"
        )
        raise api_error(403, code, "账号当前无法登录")
    auth_session, raw = create_user_session(
        session,
        user,
        device_type="desktop",
        user_agent=request.headers.get("user-agent", ""),
    )
    pairing.exchanged_at = utcnow()
    pairing.status = "consumed"
    session.commit()
    set_session_cookie(response, raw, request=request)
    response.delete_cookie(
        PAIRING_COOKIE, path="/", secure=cookie_secure(request), samesite="lax"
    )
    return auth_user_read(user, auth_session.csrf_token)


@router.post("/api/bootstrap/admin-pairings/{pairing_id}/exchange", response_model=AuthUserRead)
def exchange_admin_pairing(
    pairing_id: str, request: Request, response: Response, session: DbSession
) -> AuthUserRead:
    return exchange_pairing(pairing_id, request, response, session, "admin")


@router.post("/api/auth/pairings/{pairing_id}/exchange", response_model=AuthUserRead)
def exchange_login_pairing(
    pairing_id: str, request: Request, response: Response, session: DbSession
) -> AuthUserRead:
    return exchange_pairing(pairing_id, request, response, session, "login")


@router.get("/auth/wechat/start")
def wechat_start(
    session: DbSession,
    pairing_id: str | None = None,
    claim: str | None = None,
    next_path: str = Query(default="/dashboard", alias="next"),
) -> RedirectResponse:
    system = get_or_create_system_settings(session)
    app_id, _, public_base_url = require_oauth_settings(system)
    pairing = None
    purpose = "regular_base"
    scope = "snsapi_base"
    if pairing_id or claim:
        if not pairing_id or not claim:
            raise api_error(400, "PAIRING_INVALID", "登录二维码参数不完整")
        pairing = session.get(LoginPairing, pairing_id)
        if (
            pairing is None
            or pairing.claim_hash != hash_token(claim)
            or pairing.status != "pending"
            or as_utc(pairing.expires_at) <= utcnow()
        ):
            raise api_error(410, "PAIRING_EXPIRED", "登录二维码无效或已过期")
        purpose = "admin_userinfo" if pairing.kind == "admin" else "login_base"
        scope = "snsapi_userinfo" if pairing.kind == "admin" else "snsapi_base"
        pairing.status = "scanning"
    elif system.setup_state != "initialized":
        raise api_error(409, "SYSTEM_NOT_INITIALIZED", "系统尚未完成初始化")
    state = create_oauth_state(
        session,
        purpose=purpose,
        pairing_id=pairing.id if pairing else None,
        expected_openid=None,
        next_path=next_path,
    )
    redirect_uri = f"{public_base_url}/auth/wechat/callback"
    return RedirectResponse(build_oauth_url(app_id, redirect_uri, state, scope))

@router.get("/auth/wechat/refresh")
def refresh_wechat_profile(user: CurrentUser, session: DbSession) -> RedirectResponse:
    system = get_or_create_system_settings(session)
    app_id, _, public_base_url = require_oauth_settings(system)
    state = create_oauth_state(
        session,
        purpose="profile_refresh_userinfo",
        pairing_id=None,
        expected_openid=user.openid,
        next_path="/profile",
    )
    return RedirectResponse(
        build_oauth_url(
            app_id,
            f"{public_base_url}/auth/wechat/callback",
            state,
            "snsapi_userinfo",
        )
    )


def close_oauth_attempt(session: Session, state_row: OAuthState) -> None:
    """Consume an OAuth state and stop any browser pairing that cannot finish."""
    if state_row.consumed_at is None:
        state_row.consumed_at = utcnow()
    if state_row.pairing_id:
        pairing = session.get(LoginPairing, state_row.pairing_id)
        if pairing and pairing.status in {
            "pending",
            "scanning",
            "profile_pending",
            "awaiting_approval",
            "ready",
        }:
            pairing.status = "expired"
    session.commit()


@router.get("/auth/wechat/callback")
def wechat_callback(
    request: Request, session: DbSession, state: str, code: str | None = None
) -> RedirectResponse:
    state_row = session.scalar(
        select(OAuthState).where(OAuthState.state_hash == hash_token(state))
    )
    if (
        state_row is None
        or state_row.consumed_at is not None
        or as_utc(state_row.expires_at) <= utcnow()
    ):
        raise api_error(400, "OAUTH_STATE_INVALID", "微信授权状态无效或已经使用")
    if not code or code == "authdeny":
        close_oauth_attempt(session, state_row)
        return RedirectResponse("/login?error=oauth_denied")
    state_row.consumed_at = utcnow()
    session.commit()

    system = get_or_create_system_settings(session)
    app_id, app_secret, public_base_url = require_oauth_settings(system)
    try:
        token = exchange_oauth_code(app_id, app_secret, code)
    except WeChatError:
        close_oauth_attempt(session, state_row)
        return RedirectResponse("/login?error=wechat_oauth_failed")
    openid = str(token["openid"])
    if state_row.expected_openid and state_row.expected_openid != openid:
        close_oauth_attempt(session, state_row)
        raise api_error(400, "OPENID_MISMATCH", "两次微信授权身份不一致")

    pairing = session.get(LoginPairing, state_row.pairing_id) if state_row.pairing_id else None
    user = session.scalar(select(User).where(User.openid == openid))
    if state_row.purpose in {"regular_base", "login_base"} and user is None:
        raw = create_oauth_state(
            session,
            purpose=(
                "regular_userinfo"
                if state_row.purpose == "regular_base"
                else "login_userinfo"
            ),
            pairing_id=state_row.pairing_id,
            expected_openid=openid,
            next_path=state_row.next_path,
        )
        return RedirectResponse(
            build_oauth_url(
                app_id,
                f"{public_base_url}/auth/wechat/callback",
                raw,
                "snsapi_userinfo",
            )
        )

    profile: dict[str, object] = {}
    if state_row.purpose.endswith("userinfo"):
        try:
            profile = fetch_oauth_profile(str(token["access_token"]), openid)
        except WeChatError:
            profile = {}

    is_admin_setup = state_row.purpose == "admin_userinfo"
    if is_admin_setup:
        if system.setup_state not in {"system_configured", "admin_binding"}:
            raise api_error(409, "BOOTSTRAP_CLOSED", "管理员初始化已经完成")
        if user is not None and user.role != "admin":
            raise api_error(409, "OPENID_ALREADY_REGISTERED", "该微信身份已经注册")
    if user is None:
        user = User(
            id=str(uuid.uuid4()),
            openid=openid,
            unionid=str(profile["unionid"]) if profile.get("unionid") else None,
            nickname=normalize_wechat_text(profile["nickname"])[:64] if profile.get("nickname") else None,
            role="admin" if is_admin_setup else "user",
            status="profile_pending",
            profile_authorized_at=utcnow() if profile else None,
        )
        session.add(user)
        session.flush()
    elif user.status == "disabled":
        set_pairing_from_user(pairing, user)
        session.commit()
        return RedirectResponse("/login?error=account_disabled")

    if profile.get("nickname"):
        user.nickname = normalize_wechat_text(profile["nickname"])[:64]
    if profile.get("unionid"):
        user.unionid = str(profile["unionid"])
    if profile.get("headimgurl") and (
        not user.avatar_storage_name
        or state_row.purpose == "profile_refresh_userinfo"
    ):
        old_avatar = (
            avatar_path(user.id, user.avatar_storage_name)
            if user.avatar_storage_name
            else None
        )
        downloaded_avatar = download_wechat_avatar(
            user.id, str(profile["headimgurl"])
        )
        if downloaded_avatar:
            user.avatar_storage_name = downloaded_avatar
            if old_avatar and old_avatar.name != downloaded_avatar:
                old_avatar.unlink(missing_ok=True)
    profile_complete = bool(user.nickname and user.avatar_storage_name)
    if profile_complete:
        if is_admin_setup:
            user.status = "active"
        elif user.status not in {"active", "pending", "rejected"}:
            user.status = "pending"
    else:
        user.status = "profile_pending"
    if is_admin_setup and profile_complete:
        system.setup_state = "initialized"
    get_or_create_settings(session, user.id)
    set_pairing_from_user(pairing, user)
    session.commit()

    auth_session, raw_session = create_user_session(
        session,
        user,
        device_type="mobile",
        user_agent=request.headers.get("user-agent", ""),
    )
    if user.status == "profile_pending":
        target = "/onboarding/profile"
    elif user.status in {"pending", "rejected"}:
        target = "/pending"
    elif user.role == "admin":
        target = "/admin"
    else:
        target = state_row.next_path
    response = RedirectResponse(target)
    set_session_cookie(response, raw_session, request=request)
    return response


@router.get("/api/auth/me", response_model=AuthUserRead)
def auth_me(request: Request, session: DbSession) -> AuthUserRead:
    user, auth_session = resolve_session(request, session)
    return auth_user_read(user, auth_session.csrf_token)


@router.post("/api/auth/logout", status_code=204)
def logout(request: Request, response: Response, session: DbSession) -> None:
    try:
        _, auth_session = resolve_session(request, session)
        auth_session.revoked_at = utcnow()
        session.commit()
    finally:
        clear_session_cookie(response, request=request)


@router.get("/api/auth/sessions", response_model=list[SessionRead])
def list_sessions(
    request: Request, user: CurrentUser, session: DbSession
) -> list[SessionRead]:
    current_id = request.state.auth_session.id
    rows = session.scalars(
        select(UserSession)
        .where(UserSession.user_id == user.id, UserSession.revoked_at.is_(None))
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
            current=row.id == current_id,
        )
        for row in rows
    ]


@router.delete("/api/auth/sessions/{session_id}", status_code=204)
def revoke_session(
    session_id: str,
    request: Request,
    response: Response,
    user: CurrentUser,
    session: DbSession,
) -> None:
    row = session.scalar(
        select(UserSession).where(
            UserSession.id == session_id,
            UserSession.user_id == user.id,
            UserSession.revoked_at.is_(None),
        )
    )
    if row is None:
        raise api_error(404, "SESSION_NOT_FOUND", "设备会话不存在")
    row.revoked_at = utcnow()
    session.commit()
    if row.id == request.state.auth_session.id:
        clear_session_cookie(response, request=request)


@router.get("/api/auth/avatar/{user_id}", response_class=FileResponse)
def get_avatar(user_id: str, user: CurrentUser, session: DbSession) -> FileResponse:
    target = session.get(User, user_id)
    if target is None or not target.avatar_storage_name:
        raise api_error(404, "AVATAR_NOT_FOUND", "头像不存在")
    path = avatar_path(target.id, target.avatar_storage_name)
    if not path.is_file():
        raise api_error(404, "AVATAR_NOT_FOUND", "头像不存在")
    return FileResponse(path)


@router.put("/api/onboarding/profile", response_model=AuthUserRead)
async def complete_profile(
    request: Request,
    session: DbSession,
    user: CurrentUser,
    nickname: Annotated[str, Form(min_length=1, max_length=64)],
    avatar: Annotated[UploadFile | None, File()] = None,
) -> AuthUserRead:
    user.nickname = nickname.strip()
    if not user.nickname:
        raise api_error(422, "VALIDATION_ERROR", "昵称不能为空")
    if avatar is not None:
        content = await avatar.read(MAX_AVATAR_BYTES + 1)
        await avatar.close()
        try:
            storage_name, _ = store_avatar(user.id, content)
        except InvalidAvatar as exc:
            raise api_error(422, "INVALID_AVATAR", str(exc)) from exc
        old = avatar_path(user.id, user.avatar_storage_name) if user.avatar_storage_name else None
        user.avatar_storage_name = storage_name
        if old:
            old.unlink(missing_ok=True)
    if not user.avatar_storage_name:
        raise api_error(422, "AVATAR_REQUIRED", "请上传头像")

    system = get_or_create_system_settings(session)
    if user.role == "admin" and system.setup_state == "admin_binding":
        user.status = "active"
        system.setup_state = "initialized"
        pairing = session.scalar(
            select(LoginPairing)
            .where(LoginPairing.kind == "admin", LoginPairing.user_id == user.id)
            .order_by(LoginPairing.created_at.desc())
        )
        if pairing:
            pairing.status = "ready"
    elif user.status == "profile_pending":
        user.status = "pending"
        for pairing in session.scalars(
            select(LoginPairing).where(
                LoginPairing.kind == "login",
                LoginPairing.user_id == user.id,
                LoginPairing.status == "profile_pending",
            )
        ):
            pairing.status = "awaiting_approval"
            pairing.expires_at = utcnow() + timedelta(minutes=30)
    session.commit()
    return auth_user_read(user, request.state.auth_session.csrf_token)


@router.get("/api/onboarding/status", response_model=AuthUserRead)
def onboarding_status(request: Request, user: CurrentUser) -> AuthUserRead:
    return auth_user_read(user, request.state.auth_session.csrf_token)


@router.get("/api/onboarding/status/stream")
async def onboarding_status_stream(
    request: Request, user: CurrentUser
) -> StreamingResponse:
    async def events():
        last = ""
        while not await request.is_disconnected():
            from app.database import SessionLocal

            with SessionLocal() as session:
                fresh = session.get(User, user.id)
                status = fresh.status if fresh else "deleted"
                reason = fresh.rejection_reason if fresh else None
            payload = json.dumps(
                {"status": status, "rejection_reason": reason}, ensure_ascii=False
            )
            if payload != last:
                yield f"event: status\ndata: {payload}\n\n"
                last = payload
            if status in {"active", "rejected", "disabled", "deleted"}:
                return
            await asyncio.sleep(2)

    return StreamingResponse(events(), media_type="text/event-stream")
