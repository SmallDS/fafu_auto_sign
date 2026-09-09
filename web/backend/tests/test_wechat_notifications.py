from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from app.main import app
from app.repository import get_or_create_settings, settings_to_read, update_settings
from app.schemas import SettingsUpdate
from fafu_auto_sign.services.notification_service import NotificationService


def test_wechat_secrets_are_masked_preserved_cleared_and_validate_enable(db_session: Session) -> None:
    settings = update_settings(
        db_session,
        SettingsUpdate(
            wechat_test_app_id="wx-app-id",
            wechat_test_app_secret="super-secret-value",
            wechat_test_template_id="template-id",
            wechat_test_openid="openid-secret-value",
            wechat_test_enabled=True,
        ),
    )
    public = settings_to_read(db_session, settings)
    assert public.wechat_test_enabled is True
    assert public.has_wechat_test_app_secret is True
    assert public.has_wechat_test_openid is True
    assert public.wechat_test_app_secret_masked != settings.wechat_test_app_secret
    assert public.wechat_test_openid_masked != settings.wechat_test_openid
    assert "super-secret-value" not in public.model_dump_json()
    assert "openid-secret-value" not in public.model_dump_json()

    preserved = update_settings(
        db_session,
        SettingsUpdate(wechat_test_app_secret="", wechat_test_openid=None),
    )
    assert preserved.wechat_test_app_secret == "super-secret-value"
    assert preserved.wechat_test_openid == "openid-secret-value"

    cleared = update_settings(
        db_session,
        SettingsUpdate(clear_wechat_test_app_secret=True, clear_wechat_test_openid=True),
    )
    assert cleared.wechat_test_enabled is False
    assert cleared.wechat_test_app_secret is None
    assert cleared.wechat_test_openid is None


def test_wechat_enable_requires_all_four_values(db_session: Session) -> None:
    try:
        update_settings(
            db_session,
            SettingsUpdate(wechat_test_enabled=True, wechat_test_app_id="wx-app-id"),
        )
    except ValueError as exc:
        assert "完整配置" in str(exc)
    else:
        raise AssertionError("incomplete WeChat settings must be rejected")


def test_wechat_test_api_is_independent_and_returns_submitted(monkeypatch) -> None:
    with TestClient(app) as client:
        client.put("/api/settings", json={
            "wechat_test_enabled": False,
            "clear_wechat_test_app_secret": True,
            "clear_wechat_test_openid": True,
        })
        missing = client.post("/api/notifications/wechat-test/test")
        assert missing.status_code == 409
        assert "secret" not in missing.text.lower()
        assert "openid" not in missing.text.lower()

        saved = client.put("/api/settings", json={
            "wechat_test_enabled": True,
            "wechat_test_app_id": "wx-app-id",
            "wechat_test_app_secret": "super-secret-value",
            "wechat_test_template_id": "template-id",
            "wechat_test_openid": "openid-secret-value",
        })
        assert saved.status_code == 200
        assert "super-secret-value" not in saved.text
        assert "openid-secret-value" not in saved.text
        monkeypatch.setattr(NotificationService, "notify", lambda *args, **kwargs: True)
        response = client.post("/api/notifications/wechat-test/test")
        assert response.status_code == 200
        assert response.json()["message"] == "测试号通知已提交"


def test_migration_removes_legacy_notification_columns_and_preserves_data(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "migration.db"
    backend_dir = Path(__file__).resolve().parents[1]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")

    command.upgrade(config, "0002_wechat_test_account_notifications")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            INSERT INTO settings (
                id, user_token, jitter, heartbeat_interval, log_level,
                notification_enabled, serverchan_key, task_keywords_json,
                image_mode, worker_enabled, config_version, created_at, updated_at,
                wechat_test_enabled, wechat_test_app_id, wechat_test_app_secret,
                wechat_test_template_id, wechat_test_openid
            ) VALUES (
                1, '2_preserved', 0.00005, 900, 'INFO',
                1, 'legacy-key', '["晚归"]',
                'single', 1, 7, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                1, 'wx-app-id', 'app-secret', 'template-id', 'openid'
            )
            """
        )

    command.upgrade(config, "head")

    columns = {column["name"] for column in inspect(engine).get_columns("settings")}
    assert "notification_enabled" not in columns
    assert "serverchan_key" not in columns
    assert {
        "wechat_test_enabled",
        "wechat_test_app_id",
        "wechat_test_app_secret",
        "wechat_test_template_id",
        "wechat_test_openid",
    } <= columns
    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            """
            SELECT user_token, config_version, wechat_test_app_id,
                   wechat_test_template_id, wechat_test_openid
            FROM settings WHERE id = 1
            """
        ).one()
    assert tuple(row) == ("2_preserved", 7, "wx-app-id", "template-id", "openid")