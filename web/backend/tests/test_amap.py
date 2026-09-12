from __future__ import annotations

from collections.abc import Generator
from types import SimpleNamespace

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.amap_proxy as amap_proxy
from app.auth import active_user
from app.database import Base, get_db
from app.main import app
from app.repository import (
    get_or_create_settings,
    get_or_create_system_settings,
    system_settings_to_read,
    update_system_settings,
)
from app.schemas import SystemSettingsUpdate


class FakeUpstreamResponse:
    status_code = 200
    content = b'{"status":"1"}'
    headers = {"content-type": "application/json"}

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        yield self.content

    def close(self) -> None:
        return None


@pytest.fixture
def api_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def configured_system(session: Session):
    row = get_or_create_system_settings(session)
    row.setup_state = "initialized"
    row.public_base_url = "https://example.com"
    row.wechat_app_id = "wx-test"
    row.wechat_app_secret = "secret"
    row.wechat_template_id = "template"
    session.commit()
    return update_system_settings(
        session,
        SystemSettingsUpdate(
            amap_enabled=True,
            amap_js_key="browser-visible-key",
            amap_security_js_code="server-only-code",
        ),
    )


def install_overrides(session: Session) -> None:
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[active_user] = lambda: SimpleNamespace(id="user-1")


def test_system_amap_secret_is_masked_preserved_and_cleared(api_session: Session) -> None:
    row = configured_system(api_session)
    public = system_settings_to_read(row)
    assert public.amap_js_key == "browser-visible-key"
    assert public.has_amap_security_js_code is True
    assert "server-only-code" not in (public.amap_security_js_code_masked or "")

    kept = update_system_settings(api_session, SystemSettingsUpdate(amap_enabled=True))
    assert kept.amap_security_js_code == "server-only-code"

    cleared = update_system_settings(
        api_session, SystemSettingsUpdate(clear_amap_security_js_code=True)
    )
    assert cleared.amap_security_js_code is None
    assert cleared.amap_enabled is False


def test_enabling_amap_requires_both_credentials(api_session: Session) -> None:
    with pytest.raises(ValueError, match="完整配置"):
        update_system_settings(api_session, SystemSettingsUpdate(amap_enabled=True))


def test_map_config_and_proxy_use_global_secret_and_user_jitter(
    api_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured_system(api_session)
    get_or_create_settings(api_session, "user-1").jitter = 0.00012
    api_session.commit()
    captured: dict[str, object] = {}

    def fake_get(url: str, **kwargs: object) -> FakeUpstreamResponse:
        captured["url"] = url
        captured.update(kwargs)
        return FakeUpstreamResponse()

    monkeypatch.setattr(amap_proxy.requests, "get", fake_get)
    install_overrides(api_session)
    try:
        client = TestClient(app)
        config = client.get("/api/map/config")
        response = client.get(
            "/_AMapService/v3/geocode/regeo",
            params={"location": "118.1,25.1", "jscode": "attacker"},
        )
    finally:
        app.dependency_overrides.clear()

    assert config.status_code == 200
    assert config.json()["jitter"] == 0.00012
    assert "server-only-code" not in config.text
    assert response.status_code == 200
    params = dict(captured["params"])
    assert params["jscode"] == "server-only-code"


def test_amap_proxy_rejects_unlisted_path_before_network(
    api_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured_system(api_session)
    called = False

    def unexpected(*args: object, **kwargs: object):
        nonlocal called
        called = True
        return FakeUpstreamResponse()

    monkeypatch.setattr(amap_proxy.requests, "get", unexpected)
    install_overrides(api_session)
    try:
        response = TestClient(app).get("/_AMapService/v3/direction/driving")
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 404
    assert called is False


def test_amap_proxy_network_error_does_not_echo_secret(
    api_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured_system(api_session)

    def failed(*args: object, **kwargs: object):
        raise requests.Timeout("server-only-code")

    monkeypatch.setattr(amap_proxy.requests, "get", failed)
    install_overrides(api_session)
    try:
        response = TestClient(app).get(
            "/_AMapService/v3/assistant/coordinate/convert",
            params={"locations": "118.1,25.1", "coordsys": "gps"},
        )
    finally:
        app.dependency_overrides.clear()
    assert response.status_code == 502
    assert "server-only-code" not in response.text