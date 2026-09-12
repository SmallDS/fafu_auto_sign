from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi import HTTPException, Response
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from starlette.requests import Request

import app.auth_routes as auth_routes
from app.admin_routes import ensure_last_admin_safe
from app.auth import create_user_session, hash_token
from app.auth_routes import create_pairing, wechat_callback, wechat_start
from app.main import app
from app.models import Image, LoginPairing, OAuthState, User, UserSession
from app.repository import (
    get_or_create_settings,
    get_or_create_system_settings,
    update_settings,
)
from app.schemas import SettingsUpdate


def request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/auth/wechat/callback",
            "headers": [(b"user-agent", b"pytest-mobile")],
            "query_string": b"",
            "server": ("testserver", 443),
            "scheme": "https",
        }
    )


def user(session: Session, suffix: str, role: str = "user", status: str = "active") -> User:
    row = User(
        id=str(uuid.uuid4()),
        openid="openid-" + suffix,
        nickname="用户" + suffix,
        avatar_storage_name="avatar.jpg",
        role=role,
        status=status,
    )
    session.add(row)
    session.commit()
    return row


def configure_system(session: Session, state: str = "initialized") -> None:
    row = get_or_create_system_settings(session)
    row.setup_state = state
    row.public_base_url = "https://example.com"
    row.wechat_app_id = "wx-test"
    row.wechat_app_secret = "secret"
    row.wechat_template_id = "template"
    session.commit()


def test_session_stores_hash_and_limits_each_user_to_ten(db_session: Session) -> None:
    account = user(db_session, "sessions")
    raw_values = []
    for index in range(11):
        row, raw = create_user_session(
            db_session,
            account,
            device_type="desktop",
            user_agent="device-" + str(index),
        )
        raw_values.append(raw)
        assert row.token_hash == hash_token(raw)
        assert raw not in row.token_hash
    active = db_session.scalar(
        select(func.count(UserSession.id)).where(
            UserSession.user_id == account.id,
            UserSession.revoked_at.is_(None),
        )
    )
    assert active == 10


def test_settings_and_images_are_isolated_by_user(db_session: Session) -> None:
    first = user(db_session, "one")
    second = user(db_session, "two")
    update_settings(db_session, SettingsUpdate(user_token="2_first"), first.id)
    update_settings(db_session, SettingsUpdate(user_token="2_second"), second.id)
    assert get_or_create_settings(db_session, first.id).user_token == "2_first"
    assert get_or_create_settings(db_session, second.id).user_token == "2_second"

    foreign = Image(
        id=str(uuid.uuid4()),
        user_id=second.id,
        purpose="library",
        original_name="other.png",
        storage_name="other.png",
        mime_type="image/png",
        size=1,
        sha256="a" * 64,
    )
    db_session.add(foreign)
    db_session.commit()
    with pytest.raises(ValueError, match="图片"):
        update_settings(
            db_session,
            SettingsUpdate(image_mode="single", selected_image_id=foreign.id),
            first.id,
        )


def test_cross_user_image_and_history_ids_return_not_found(
    db_session: Session,
) -> None:
    from app.auth import active_user
    from app.database import get_db
    from app.models import RunHistory, utcnow

    first = user(db_session, "owner")
    second = user(db_session, "attacker")
    image = Image(
        id=str(uuid.uuid4()),
        user_id=first.id,
        purpose="library",
        original_name="secret.png",
        storage_name="secret.png",
        mime_type="image/png",
        size=1,
        sha256="b" * 64,
    )
    now = auth_routes.utcnow()
    run = RunHistory(
        user_id=first.id,
        trigger="manual",
        config_version=1,
        started_at=now,
        finished_at=now,
        status="success",
        summary="ok",
        task_details_json="[]",
    )
    db_session.add_all([image, run])
    db_session.commit()
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[active_user] = lambda: second
    try:
        client = TestClient(app)
        assert client.get("/api/images/" + image.id).status_code == 404
        assert client.get("/api/runs/" + str(run.id)).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_last_active_admin_cannot_be_removed_or_demoted(db_session: Session) -> None:
    admin = user(db_session, "admin", role="admin")
    with pytest.raises(HTTPException) as caught:
        ensure_last_admin_safe(db_session, admin)
    assert caught.value.status_code == 409

    user(db_session, "admin2", role="admin")
    ensure_last_admin_safe(db_session, admin, changing_role=True)


def test_admin_oauth_pairing_consumes_state_and_initializes(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_system(db_session, "system_configured")
    cookie_response = Response()
    pairing_result = create_pairing(
        db_session, cookie_response, kind="admin", ttl_seconds=300
    )
    pairing = db_session.get(LoginPairing, pairing_result.id)
    assert pairing is not None
    parsed = parse_qs(urlparse(pairing_result.auth_url or "").query)
    claim = parsed["claim"][0]
    assert pairing.claim_hash == hash_token(claim)
    assert claim not in pairing.verifier_hash

    redirect = wechat_start(
        session=db_session,
        pairing_id=pairing.id,
        claim=claim,
        next_path="/dashboard",
    )
    state = parse_qs(urlparse(redirect.headers["location"]).query)["state"][0]
    stored_state = db_session.scalar(
        select(OAuthState).where(OAuthState.state_hash == hash_token(state))
    )
    assert stored_state is not None
    assert state != stored_state.state_hash

    monkeypatch.setattr(
        auth_routes,
        "exchange_oauth_code",
        lambda app_id, app_secret, code: {
            "openid": "admin-openid",
            "access_token": "oauth-token",
        },
    )
    monkeypatch.setattr(
        auth_routes,
        "fetch_oauth_profile",
        lambda access_token, openid: {
            "openid": openid,
            "nickname": "管理员",
            "headimgurl": "https://thirdwx.qlogo.cn/avatar",
        },
    )
    monkeypatch.setattr(
        auth_routes, "download_wechat_avatar", lambda user_id, url: "avatar.jpg"
    )
    callback = wechat_callback(request(), db_session, state=state, code="one-time-code")
    assert callback.headers["location"] == "/admin"
    admin = db_session.scalar(select(User).where(User.openid == "admin-openid"))
    assert admin is not None and admin.role == "admin" and admin.status == "active"
    assert get_or_create_system_settings(db_session).setup_state == "initialized"
    db_session.refresh(pairing)
    assert pairing.status == "ready"

    with pytest.raises(HTTPException) as replay:
        wechat_callback(request(), db_session, state=state, code="one-time-code")
    assert replay.value.status_code == 400

def test_admin_detail_resources_are_filtered_by_target_user(db_session: Session) -> None:
    from app.admin_routes import list_audit, list_user_images, list_user_runs, list_user_sessions
    from app.models import AuditLog, RunHistory, utcnow

    admin = user(db_session, "resource-admin", role="admin")
    first = user(db_session, "resource-one")
    second = user(db_session, "resource-two")
    create_user_session(
        db_session,
        first,
        device_type="desktop",
        user_agent="first-device",
    )
    create_user_session(
        db_session,
        second,
        device_type="mobile",
        user_agent="second-device",
    )
    now = utcnow()
    db_session.add_all(
        [
            Image(
                id=str(uuid.uuid4()),
                user_id=first.id,
                purpose="library",
                original_name="first.png",
                storage_name="first.png",
                mime_type="image/png",
                size=1,
                sha256="c" * 64,
            ),
            Image(
                id=str(uuid.uuid4()),
                user_id=second.id,
                purpose="library",
                original_name="second.png",
                storage_name="second.png",
                mime_type="image/png",
                size=1,
                sha256="d" * 64,
            ),
            RunHistory(
                user_id=first.id,
                trigger="manual",
                config_version=1,
                started_at=now,
                finished_at=now,
                status="success",
                summary="first-run",
                task_details_json="[]",
            ),
            AuditLog(
                actor_user_id=admin.id,
                target_user_id=first.id,
                action="first.action",
                result="success",
            ),
            AuditLog(
                actor_user_id=admin.id,
                target_user_id=second.id,
                action="second.action",
                result="success",
            ),
        ]
    )
    db_session.commit()

    sessions = list_user_sessions(first.id, admin, db_session)
    images = list_user_images(first.id, admin, db_session, page=1, page_size=20)
    runs = list_user_runs(first.id, admin, db_session, page=1, page_size=20)
    audits = list_audit(
        admin,
        db_session,
        page=1,
        page_size=20,
        target_user_id=first.id,
    )

    assert [item.user_agent for item in sessions] == ["first-device"]
    assert [item.original_name for item in images.items] == ["first.png"]
    assert [item.summary for item in runs.items] == ["first-run"]
    assert [item.action for item in audits.items] == ["first.action"]