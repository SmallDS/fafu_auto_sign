from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.fafu_auth import FafuAuthError, FafuAuthManager
from app.fafu_auth_transport import FafuAuthTransportError
from app.models import FafuAuthSession, User, utcnow
from app.repository import get_or_create_settings, settings_to_read, update_settings
from app.paths import BACKEND_DIR
from app.schemas import SettingsUpdate


class FakeTransport:
    def __init__(self) -> None:
        self.refresh_calls = 0
        self.fail_exchange = False
        self.invalid_refresh = False
        self.token_expired = False

    def begin(self, username: str, password: str) -> tuple[str, str]:
        assert password == "cas-secret"
        return "https://api.welink.huaweicloud.com/callback", "cas-cookie"

    def complete(
        self, service: str, cookie: str, code: str, device_id: str
    ) -> tuple[str, str, str]:
        assert cookie == "cas-cookie" and code == "123456"
        assert device_id == "bound-device"
        return "welink-one", "refresh-one", "2_auto-one"

    def validate_token(self, token: str) -> str:
        return "expired" if self.token_expired and token == "2_auto-one" else "valid"

    def refresh_welink(self, refresh_token: str) -> tuple[str, str]:
        self.refresh_calls += 1
        if self.invalid_refresh:
            raise FafuAuthTransportError("INVALID_REFRESH", "需要重新连接")
        assert refresh_token in {"refresh-one", "refresh-two"}
        return "welink-two", "refresh-two"

    def exchange_welink(self, we_link_token: str, device_id: str) -> str:
        if self.fail_exchange:
            raise FafuAuthTransportError("UPSTREAM_UNAVAILABLE", "暂时不可用")
        assert we_link_token == "welink-two" and device_id == "bound-device"
        return "2_auto-two"


def create_user(session: Session, suffix: str) -> User:
    row = User(
        id=str(uuid.uuid4()), openid="auth-" + suffix,
        nickname=suffix, role="user", status="active",
    )
    session.add(row)
    session.commit()
    return row


def bind(manager: FafuAuthManager, session: Session, user_id: str) -> str:
    attempt = manager.start(user_id, "20260001", "cas-secret", "bound-device")
    manager.complete(session, user_id, attempt.id, "123456")
    return attempt.id


def test_complete_is_one_time_and_cross_user_safe(db_session: Session) -> None:
    first = create_user(db_session, "first")
    second = create_user(db_session, "second")
    manager = FafuAuthManager(FakeTransport())
    update_settings(db_session, SettingsUpdate(user_token="2_manual-old"), first.id)
    attempt = manager.start(first.id, "20260001", "cas-secret", "bound-device")

    with pytest.raises(FafuAuthError) as foreign:
        manager.complete(db_session, second.id, attempt.id, "123456")
    assert foreign.value.code == "AUTH_ATTEMPT_NOT_FOUND"
    assert db_session.get(FafuAuthSession, first.id) is None

    manager.complete(db_session, first.id, attempt.id, "123456")
    settings = get_or_create_settings(db_session, first.id)
    assert settings.fafu_auth_mode == "auto"
    assert settings.user_token == "2_auto-one"
    public = settings_to_read(db_session, settings).model_dump()
    assert public["fafu_auth_status"] == "connected"
    assert "cas-secret" not in str(public)
    assert "refresh-one" not in str(public)
    assert "20260001" not in str(public)
    with pytest.raises(FafuAuthError) as replay:
        manager.complete(db_session, first.id, attempt.id, "123456")
    assert replay.value.code == "AUTH_ATTEMPT_NOT_FOUND"


def test_expired_attempt_keeps_manual_config(db_session: Session) -> None:
    account = create_user(db_session, "expired")
    manager = FafuAuthManager(FakeTransport())
    update_settings(db_session, SettingsUpdate(user_token="2_manual-old"), account.id)
    attempt = manager.start(account.id, "20260001", "cas-secret", "bound-device")
    manager._attempts[attempt.id] = attempt.__class__(
        **{**attempt.__dict__, "expires_at": utcnow() - timedelta(seconds=1)}
    )
    with pytest.raises(FafuAuthError) as expired:
        manager.complete(db_session, account.id, attempt.id, "123456")
    assert expired.value.code == "AUTH_ATTEMPT_EXPIRED"
    assert get_or_create_settings(db_session, account.id).user_token == "2_manual-old"
    assert db_session.get(FafuAuthSession, account.id) is None


def test_manual_switch_and_clear_delete_auto_credentials(db_session: Session) -> None:
    account = create_user(db_session, "switch")
    manager = FafuAuthManager(FakeTransport())
    bind(manager, db_session, account.id)
    update_settings(db_session, SettingsUpdate(user_token="2_manual-new"), account.id)
    assert db_session.get(FafuAuthSession, account.id) is None
    settings = get_or_create_settings(db_session, account.id)
    assert settings.fafu_auth_mode == "manual" and settings.user_token == "2_manual-new"
    update_settings(db_session, SettingsUpdate(clear_user_token=True), account.id)
    assert settings.user_token is None and settings.worker_enabled is False
    assert settings_to_read(db_session, settings).fafu_auth_mode is None


def test_rotated_refresh_token_survives_exchange_failure(db_session: Session) -> None:
    account = create_user(db_session, "rotation")
    transport = FakeTransport()
    manager = FafuAuthManager(transport)
    bind(manager, db_session, account.id)
    transport.token_expired = True
    transport.fail_exchange = True
    with pytest.raises(FafuAuthError) as failed:
        manager.ensure_token(db_session, account.id)
    assert failed.value.code == "UPSTREAM_UNAVAILABLE"
    auth = db_session.get(FafuAuthSession, account.id)
    assert auth.refresh_token == "refresh-two"
    assert auth.next_refresh_after is not None
    assert transport.refresh_calls == 1
    with pytest.raises(FafuAuthError) as backoff:
        manager.ensure_token(db_session, account.id)
    assert backoff.value.code == "REFRESH_BACKOFF"
    assert transport.refresh_calls == 1


def test_invalid_refresh_pauses_only_affected_user(db_session: Session) -> None:
    first = create_user(db_session, "bad-refresh")
    second = create_user(db_session, "healthy")
    transport = FakeTransport()
    manager = FafuAuthManager(transport)
    bind(manager, db_session, first.id)
    update_settings(db_session, SettingsUpdate(user_token="2_other"), second.id)
    transport.token_expired = True
    transport.invalid_refresh = True
    with pytest.raises(FafuAuthError) as failed:
        manager.ensure_token(db_session, first.id)
    assert failed.value.code == "RECONNECT_REQUIRED"
    assert get_or_create_settings(db_session, first.id).worker_enabled is False
    assert get_or_create_settings(db_session, second.id).worker_enabled is True
    assert db_session.get(FafuAuthSession, first.id).resume_worker_after_reconnect is True
    transport.invalid_refresh = False
    transport.token_expired = False
    reconnect_attempt = manager.reconnect(db_session, first.id)
    manager.complete(db_session, first.id, reconnect_attempt.id, "123456")
    assert get_or_create_settings(db_session, first.id).worker_enabled is True


def test_concurrent_refresh_rotates_once(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite:///{(tmp_path / 'auth.db').as_posix()}")
    Base.metadata.create_all(engine)
    maker = sessionmaker(engine, expire_on_commit=False, autoflush=False)
    transport = FakeTransport()
    manager = FafuAuthManager(transport)
    with maker() as session:
        account = create_user(session, "concurrent")
        bind(manager, session, account.id)
        user_id = account.id
    transport.token_expired = True

    def renew() -> str:
        with maker() as session:
            return manager.ensure_token(session, user_id)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: renew(), range(2)))
    assert results == ["2_auto-two", "2_auto-two"]
    assert transport.refresh_calls == 1
    with maker() as session:
        auth = session.get(FafuAuthSession, user_id)
        assert auth.refresh_token == "refresh-two"
    engine.dispose()


def test_migration_0007_preserves_manual_token(tmp_path: Path) -> None:
    db_path = tmp_path / "migration.db"
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite:///{db_path.as_posix()}")
    command.upgrade(config, "0006_multi_user_auth")
    engine = create_engine(f"sqlite:///{db_path.as_posix()}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO users (id, openid, role, status, created_at, updated_at) "
            "VALUES ('u1', 'openid-migrate', 'user', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
        connection.exec_driver_sql(
            "INSERT INTO settings (user_id, user_token, jitter, heartbeat_interval, "
            "log_level, amap_enabled, amap_source_coordinate_system, wechat_test_enabled, "
            "notification_enabled, task_keywords_json, image_mode, worker_enabled, "
            "config_version, created_at, updated_at) VALUES "
            "('u1', '2_existing', 0.00005, 900, 'INFO', 0, 'gcj02', 0, 1, "
            "'[]', 'single', 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        )
    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT user_token, fafu_auth_mode FROM settings WHERE user_id='u1'"
        ).one()
        assert row == ("2_existing", "manual")
        assert connection.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE name='fafu_auth_sessions'"
        ).scalar_one() == "fafu_auth_sessions"
    engine.dispose()
