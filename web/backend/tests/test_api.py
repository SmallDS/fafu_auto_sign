from __future__ import annotations

import base64
import io
import uuid

import pytest
from fastapi.testclient import TestClient
from PIL import Image as PillowImage
from sqlalchemy import delete

import app.auth_routes as auth_routes
from app.auth import SESSION_COOKIE, create_user_session
from app.database import SessionLocal
from app.fafu_auth import fafu_auth
from app.main import app
from app.models import (
    AuditLog,
    Image,
    LoginPairing,
    OAuthState,
    RunHistory,
    Settings,
    SignJob,
    SystemSettings,
    User,
    UserSession,
)
from app.repository import get_or_create_settings, get_or_create_system_settings


def png_bytes() -> bytes:
    output = io.BytesIO()
    PillowImage.new("RGB", (2, 2), color="green").save(output, format="PNG")
    return output.getvalue()


def reset_database() -> None:
    with SessionLocal() as session:
        for model in (
            AuditLog, SignJob, OAuthState, LoginPairing, UserSession,
            RunHistory, Image, Settings, User, SystemSettings,
        ):
            session.execute(delete(model))
        session.commit()


def login_active_user(client: TestClient) -> tuple[User, str]:
    with SessionLocal() as session:
        system = get_or_create_system_settings(session)
        system.setup_state = "initialized"
        system.public_base_url = "https://example.com"
        user = User(
            id=str(uuid.uuid4()),
            openid="openid-" + uuid.uuid4().hex,
            nickname="测试用户",
            role="user",
            status="active",
        )
        session.add(user)
        session.commit()
        settings = get_or_create_settings(session, user.id)
        settings.worker_enabled = False
        session.commit()
        auth_session, raw = create_user_session(
            session, user, device_type="desktop", user_agent="pytest"
        )
        csrf = auth_session.csrf_token
    client.cookies.set(SESSION_COOKIE, raw)
    return user, csrf


def test_health_is_public_and_business_api_requires_session() -> None:
    with TestClient(app, base_url="https://testserver") as client:
        reset_database()
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["setup_state"] == "uninitialized"
        protected = client.get("/api/settings")
        assert protected.status_code == 401
        assert protected.json()["detail"]["code"] == "AUTH_REQUIRED"


@pytest.mark.parametrize("scheme, secure_cookie", [("http", False), ("https", True)])
def test_pairing_login_works_on_current_origin_regardless_of_oauth_domain(
    scheme: str, secure_cookie: bool,
) -> None:
    with TestClient(app, base_url=f"{scheme}://testserver") as client:
        reset_database()
        with SessionLocal() as session:
            system = get_or_create_system_settings(session)
            system.setup_state = "initialized"
            system.public_base_url = "https://public.example.com"
            system.wechat_app_id = "wx-test"
            system.wechat_app_secret = "test-secret"
            user = User(
                id=str(uuid.uuid4()), openid="openid-" + uuid.uuid4().hex,
                nickname="测试用户", role="user", status="active",
            )
            session.add(user)
            session.commit()
            user_id = user.id

        created = client.post("/api/auth/pairings")
        assert created.status_code == 200
        assert created.json()["auth_url"].startswith("https://public.example.com/")
        assert ("secure" in created.headers["set-cookie"].lower()) is secure_cookie
        pairing_id = created.json()["id"]
        assert client.get(f"/api/auth/pairings/{pairing_id}").status_code == 200
        with SessionLocal() as session:
            pairing = session.get(LoginPairing, pairing_id)
            pairing.user_id = user_id
            pairing.status = "ready"
            session.commit()

        exchanged = client.post(f"/api/auth/pairings/{pairing_id}/exchange")
        assert exchanged.status_code == 200
        session_cookie = next(
            item for item in exchanged.headers.get_list("set-cookie")
            if item.startswith(SESSION_COOKIE + "=")
        )
        assert ("secure" in session_cookie.lower()) is secure_cookie
        assert "httponly" in session_cookie.lower()
        assert "samesite=lax" in session_cookie.lower()
        assert client.get("/api/auth/me").status_code == 200
        logged_out = client.post(
            "/api/auth/logout",
            headers={"X-CSRF-Token": exchanged.json()["csrf_token"]},
        )
        assert logged_out.status_code == 204
        assert ("secure" in logged_out.headers["set-cookie"].lower()) is secure_cookie
        assert client.get("/api/auth/me").status_code == 401


def test_https_forwarded_by_reverse_proxy_keeps_secure_cookie() -> None:
    with TestClient(app, base_url="http://testserver") as client:
        reset_database()
        with SessionLocal() as session:
            system = get_or_create_system_settings(session)
            system.setup_state = "initialized"
            system.public_base_url = "https://public.example.com"
            system.wechat_app_id = "wx-test"
            system.wechat_app_secret = "test-secret"
            session.commit()
        created = client.post(
            "/api/auth/pairings", headers={"X-Forwarded-Proto": "https"}
        )
        assert created.status_code == 200
        assert "secure" in created.headers["set-cookie"].lower()


def test_authenticated_settings_csrf_and_user_image_upload() -> None:
    with TestClient(app, base_url="https://testserver") as client:
        reset_database()
        user, csrf = login_active_user(client)
        missing_csrf = client.put("/api/settings", json={"user_token": "2_hidden"})
        assert missing_csrf.status_code == 403
        saved = client.put(
            "/api/settings",
            headers={"X-CSRF-Token": csrf},
            json={"user_token": "2_api_test", "worker_enabled": False},
        )
        assert saved.status_code == 200
        assert saved.json()["has_user_token"] is True
        assert "2_api_test" not in saved.text

        uploaded = client.post(
            "/api/images",
            headers={"X-CSRF-Token": csrf},
            data={"category": "library"},
            files={"files": ("test.png", png_bytes(), "image/png")},
        )
        assert uploaded.status_code == 201
        image_id = uploaded.json()[0]["id"]
        listed = client.get("/api/images")
        assert listed.json()["items"][0]["id"] == image_id
        with SessionLocal() as session:
            row = session.get(Image, image_id)
            assert row is not None and row.user_id == user.id


def test_fafu_auth_api_requires_csrf_and_never_returns_credentials(monkeypatch) -> None:
    class Transport:
        def begin(self, username, password):
            assert username == "20260001" and password == "cas-secret"
            return "https://api.welink.huaweicloud.com/callback", "temporary-cookie"

        def complete(self, service, cookie, code, device_id):
            assert cookie == "temporary-cookie" and code == "123456"
            assert device_id == "bound-device"
            return "welink-secret", "refresh-secret", "2_auto-secret"

        def validate_token(self, token):
            return "valid"

    monkeypatch.setattr(fafu_auth, "transport", Transport())
    with TestClient(app, base_url="https://testserver") as client:
        reset_database()
        user, csrf = login_active_user(client)
        credentials = {
            "username": "20260001", "password": "cas-secret",
            "device_id": "bound-device",
        }
        assert client.post("/api/fafu-auth/start", json=credentials).status_code == 403
        started = client.post(
            "/api/fafu-auth/start", headers={"X-CSRF-Token": csrf},
            json=credentials,
        )
        assert started.status_code == 200
        assert "cas-secret" not in started.text
        attempt_id = started.json()["attempt_id"]
        completed = client.post(
            "/api/fafu-auth/complete", headers={"X-CSRF-Token": csrf},
            json={"attempt_id": attempt_id, "code": "123456"},
        )
        assert completed.status_code == 200
        assert completed.json()["fafu_auth_mode"] == "auto"
        public = client.get("/api/settings")
        assert public.status_code == 200
        assert public.json()["fafu_auth_status"] == "connected"
        for secret in ("cas-secret", "refresh-secret", "welink-secret", "2_auto-secret"):
            assert secret not in public.text
        manual = client.put(
            "/api/settings", headers={"X-CSRF-Token": csrf},
            json={"user_token": "2_manual-next"},
        )
        assert manual.status_code == 200
        with SessionLocal() as session:
            from app.models import FafuAuthSession
            assert session.get(FafuAuthSession, user.id) is None


def test_full_authorization_is_normalized_and_invalid_value_not_echoed() -> None:
    token = "2_authorization_token"
    authorization = base64.b64encode(
        f"1773238142:nonceForWebTest1:{'b' * 32}:{token}".encode()
    ).decode()
    invalid = base64.b64encode(b"1773238142:secret:not-a-signature:2_hidden").decode()
    with TestClient(app, base_url="https://testserver") as client:
        reset_database()
        _, csrf = login_active_user(client)
        saved = client.put(
            "/api/settings",
            headers={"X-CSRF-Token": csrf},
            json={"user_token": authorization},
        )
        assert saved.status_code == 200
        rejected = client.put(
            "/api/settings",
            headers={"X-CSRF-Token": csrf},
            json={"user_token": invalid},
        )
        assert rejected.status_code == 422
        assert invalid not in rejected.text
        assert "2_hidden" not in rejected.text


def test_bootstrap_validates_then_freezes_system_configuration(monkeypatch) -> None:
    monkeypatch.setattr(
        auth_routes,
        "get_global_access_token",
        lambda app_id, app_secret: "validated-token",
    )
    payload = {
        "wechat_app_id": "wx-test",
        "wechat_app_secret": "secret",
        "wechat_template_id": "template",
        "public_base_url": "https://example.com",
        "menu_name": "签到管理",
        "amap_enabled": False,
        "log_level": "INFO",
    }
    with TestClient(app, base_url="https://testserver") as client:
        reset_database()
        first = client.put("/api/bootstrap/system", json=payload)
        assert first.status_code == 200
        assert first.json()["setup_state"] == "system_configured"
        second = client.put("/api/bootstrap/system", json=payload)
        assert second.status_code == 409
        assert second.json()["detail"]["code"] == "BOOTSTRAP_CLOSED"
