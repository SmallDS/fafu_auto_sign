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