from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session

from app.auth import active_user
from app.database import get_db
from app.main import app
from app.models import RunHistory, Settings, SystemSettings, User
from app.repository import (
    get_or_create_settings,
    get_or_create_system_settings,
    system_settings_to_read,
    update_system_settings,
)
from app.schemas import SystemSettingsUpdate
from fafu_auto_sign.services.notification_service import NotificationService


def test_system_wechat_secret_mask_preserve_clear_and_validate(db_session: Session) -> None:
    system = get_or_create_system_settings(db_session)
    system.public_base_url = "https://example.com"
    db_session.commit()
    updated = update_system_settings(
        db_session,
        SystemSettingsUpdate(
            wechat_app_id="wx-app-id",
            wechat_app_secret="super-secret-value",
            wechat_template_id="template-id",
            wechat_enabled=True,
        ),
    )
    public = system_settings_to_read(updated)
    assert public.has_wechat_app_secret is True
    assert "super-secret-value" not in (public.wechat_app_secret_masked or "")
    assert update_system_settings(
        db_session, SystemSettingsUpdate(wechat_enabled=True)
    ).wechat_app_secret == "super-secret-value"
    cleared = update_system_settings(
        db_session, SystemSettingsUpdate(clear_wechat_app_secret=True)
    )
    assert cleared.wechat_app_secret is None
    assert cleared.wechat_enabled is False

    with pytest.raises(ValueError, match="完整配置"):
        update_system_settings(
            db_session,
            SystemSettingsUpdate(
                wechat_enabled=True,
                wechat_app_id="wx-only",
                wechat_template_id="template",
            ),
        )


def test_system_settings_persist_explicit_false_flags(db_session: Session) -> None:
    system = get_or_create_system_settings(db_session)
    system.public_base_url = "https://example.com"
    system.wechat_app_id = "wx-app-id"
    system.wechat_app_secret = "secret"
    system.wechat_template_id = "template"
    system.wechat_enabled = True
    system.amap_js_key = "amap-key"
    system.amap_security_js_code = "amap-secret"
    system.amap_enabled = True
    db_session.commit()

    updated = update_system_settings(
        db_session,
        SystemSettingsUpdate(
            wechat_enabled=False,
            amap_enabled=False,
        ),
    )

    assert updated.wechat_enabled is False
    assert updated.amap_enabled is False
    db_session.expire_all()
    persisted = db_session.get(SystemSettings, 1)
    assert persisted is not None
    assert persisted.wechat_enabled is False
    assert persisted.amap_enabled is False


def test_notification_uses_system_credentials_and_current_openid(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = User(
        id=str(uuid.uuid4()),
        openid="current-openid",
        nickname="User",
        role="user",
        status="active",
    )
    db_session.add(user)
    system = get_or_create_system_settings(db_session)
    system.setup_state = "initialized"
    system.public_base_url = "https://example.com"
    system.wechat_app_id = "wx-app-id"
    system.wechat_app_secret = "secret"
    system.wechat_template_id = "template"
    system.wechat_enabled = True
    db_session.commit()
    get_or_create_settings(db_session, user.id).notification_enabled = True
    db_session.commit()

    captured = {}
    monkeypatch.setattr(
        NotificationService,
        "notify",
        lambda self, title, content, **kwargs: captured.update(
            {"config": self.config, "title": title}
        ) or True,
    )
    monkeypatch.setattr("app.main.worker.snapshot", lambda user_id: {"state": "idle"})
    app.dependency_overrides[get_db] = lambda: db_session
    app.dependency_overrides[active_user] = lambda: user
    try:
        response = TestClient(app).post("/api/notifications/wechat-test/test")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 200
    assert captured["config"].wechat_test_openid == "current-openid"
    assert captured["config"].wechat_test_app_secret == "secret"


def test_0006_migration_preserves_system_settings_and_clears_legacy_business_data(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "migration.db"
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "0005_amap_map_settings")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            INSERT INTO settings (
                id, user_token, jitter, heartbeat_interval, log_level,
                task_keywords_json, image_mode, worker_enabled, config_version,
                created_at, updated_at, wechat_test_enabled, wechat_test_app_id,
                wechat_test_app_secret, wechat_test_template_id, wechat_test_openid,
                amap_enabled, amap_js_key, amap_security_js_code,
                amap_source_coordinate_system
            ) VALUES (
                1, '2_discard', 0.00005, 900, 'WARNING', '[]', 'single', 1, 7,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, 1, 'wx-app-id',
                'app-secret', 'template-id', 'old-openid', 1, 'amap-key',
                'amap-secret', 'gcj02'
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO run_history (
                trigger, config_version, started_at, finished_at, status,
                discovered_count, success_count, failure_count, summary,
                task_details_json
            ) VALUES ('manual', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                      'success', 1, 1, 0, 'ok', '[]')
            """
        )
    command.upgrade(config, "head")

    columns = {item["name"] for item in inspect(engine).get_columns("settings")}
    assert {"user_id", "next_run_at", "notification_enabled"} <= columns
    with Session(engine) as session:
        system = session.get(SystemSettings, 1)
        assert system is not None
        assert system.setup_state == "system_configured"
        assert system.wechat_app_id == "wx-app-id"
        assert system.wechat_app_secret == "app-secret"
        assert system.amap_js_key == "amap-key"
        assert session.execute(select(SystemSettings)).scalar_one() is not None
        assert session.execute(select(User)).scalars().all() == []
        assert session.execute(select(Settings)).scalars().all() == []
        assert session.execute(select(RunHistory)).scalars().all() == []
    engine.dispose()

def test_wechat_profile_json_is_decoded_as_utf8(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import json
    import requests

    from app.wechat import fetch_oauth_profile, normalize_wechat_text

    response = requests.Response()
    response.status_code = 200
    response.headers["content-type"] = "text/plain"
    response.encoding = "ISO-8859-1"
    response._content = json.dumps(
        {"openid": "openid", "nickname": "中文昵称"}, ensure_ascii=False
    ).encode("utf-8")
    monkeypatch.setattr("app.wechat.requests.get", lambda *args, **kwargs: response)

    profile = fetch_oauth_profile("oauth-token", "openid")
    assert profile["nickname"] == "中文昵称"
    assert normalize_wechat_text("管理员".encode("utf-8").decode("latin-1")) == "管理员"
    assert normalize_wechat_text("赵".encode("utf-8").decode("latin-1")) == "赵"


def test_public_base_url_rejects_paths_and_nonstandard_ports() -> None:
    from pydantic import ValidationError

    from app.schemas import BootstrapSystemRequest

    common = {
        "wechat_app_id": "appid",
        "wechat_app_secret": "secret",
        "wechat_template_id": "template",
    }
    with pytest.raises(ValidationError):
        BootstrapSystemRequest(**common, public_base_url="https://example.com/callback")
    with pytest.raises(ValidationError):
        BootstrapSystemRequest(**common, public_base_url="https://example.com:8000")
    valid = BootstrapSystemRequest(**common, public_base_url="https://EXAMPLE.com/")
    assert valid.public_base_url == "https://example.com"

def test_menu_sync_builds_https_view_button(monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    import requests

    from app.wechat import MENU_CREATE_URL, sync_menu

    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps({"errcode": 0, "errmsg": "ok"}).encode("utf-8")
    captured: dict[str, object] = {}

    monkeypatch.setattr("app.wechat.get_global_access_token", lambda *args: "token")

    def post(url: str, **kwargs: object) -> requests.Response:
        captured.update({"url": url, **kwargs})
        return response

    monkeypatch.setattr("app.wechat.requests.post", post)
    sync_menu("appid", "secret", "https://sign.example.com", "签到管理")

    assert captured["url"] == MENU_CREATE_URL
    assert captured["params"] == {"access_token": "token"}
    assert captured["headers"] == {"Content-Type": "application/json; charset=utf-8"}
    body = captured["data"]
    assert isinstance(body, bytes)
    assert b"\\u" not in body
    assert json.loads(body.decode("utf-8")) == {
        "button": [
            {
                "type": "view",
                "name": "签到管理",
                "url": "https://sign.example.com/auth/wechat/start?next=%2Fdashboard",
            }
        ]
    }


def test_wechat_error_exposes_safe_error_code(monkeypatch: pytest.MonkeyPatch) -> None:
    import json
    import requests

    from app.wechat import WeChatError, get_global_access_token

    response = requests.Response()
    response.status_code = 200
    response._content = json.dumps(
        {"errcode": 40164, "errmsg": "sensitive upstream detail"}
    ).encode("utf-8")
    monkeypatch.setattr("app.wechat.requests.get", lambda *args, **kwargs: response)

    with pytest.raises(WeChatError, match="40164.*IP 白名单") as caught:
        get_global_access_token("appid", "secret")
    assert "sensitive upstream detail" not in str(caught.value)


def test_wechat_menu_name_enforces_primary_button_limit() -> None:
    from pydantic import ValidationError

    from app.schemas import BootstrapSystemRequest, SystemSettingsUpdate

    with pytest.raises(ValidationError, match="最多 4 个汉字"):
        SystemSettingsUpdate(menu_name="五个汉字名")
    with pytest.raises(ValidationError, match="最多 4 个汉字"):
        BootstrapSystemRequest(
            wechat_app_id="appid",
            wechat_app_secret="secret",
            wechat_template_id="template",
            public_base_url="https://example.com",
            menu_name="ninechars",
        )
    assert SystemSettingsUpdate(menu_name="签到管理").menu_name == "签到管理"

def configured_menu_admin(db_session: Session) -> User:
    administrator = User(
        id=str(uuid.uuid4()),
        openid="menu-admin-openid",
        nickname="菜单管理员",
        role="admin",
        status="active",
    )
    db_session.add(administrator)
    system = get_or_create_system_settings(db_session)
    system.setup_state = "initialized"
    system.public_base_url = "https://sign.example.com"
    system.menu_name = "签到管理"
    system.wechat_app_id = "wx-app-id"
    system.wechat_app_secret = "secret"
    system.wechat_template_id = "template"
    system.wechat_enabled = True
    db_session.commit()
    return administrator


def test_menu_sync_converts_unexpected_failure_to_structured_502(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    from app import admin_routes

    administrator = configured_menu_admin(db_session)
    monkeypatch.setattr(
        admin_routes,
        "sync_menu",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("unexpected")),
    )

    with pytest.raises(HTTPException) as caught:
        admin_routes.synchronize_menu(administrator, db_session)

    assert caught.value.status_code == 502
    assert caught.value.detail == {
        "code": "WECHAT_MENU_FAILED",
        "message": "公众号菜单同步失败，请查看服务日志后重试",
    }


def test_menu_sync_audit_failure_does_not_mask_wechat_error(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi import HTTPException

    from app import admin_routes

    administrator = configured_menu_admin(db_session)
    monkeypatch.setattr(
        admin_routes,
        "sync_menu",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            admin_routes.WeChatError("微信菜单同步失败（错误码 48001）：当前测试号没有该接口权限")
        ),
    )
    monkeypatch.setattr(
        admin_routes,
        "audit",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("audit failed")),
    )

    with pytest.raises(HTTPException) as caught:
        admin_routes.synchronize_menu(administrator, db_session)

    assert caught.value.status_code == 502
    assert caught.value.detail["code"] == "WECHAT_MENU_FAILED"
    assert "48001" in caught.value.detail["message"]
