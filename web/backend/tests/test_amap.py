from __future__ import annotations

from collections.abc import Generator
import logging

import pytest
import requests
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

import app.amap_proxy as amap_proxy
from app.database import Base, get_db
from app.main import app
from app.amap_proxy import AmapAccessLogFilter, AmapResponseTooLarge, proxy_amap_request
from app.repository import get_or_create_settings, settings_to_read, update_settings
from app.schemas import SettingsUpdate


class FakeUpstreamResponse:
    def __init__(
        self,
        body: bytes = b'{"status":"1"}',
        *,
        status_code: int = 200,
    ) -> None:
        self.body = body
        self.status_code = status_code
        self.headers = {"Content-Type": "application/json", "Cache-Control": "max-age=60"}
        self.closed = False

    def iter_content(self, chunk_size: int) -> Generator[bytes, None, None]:
        del chunk_size
        yield self.body

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def api_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine, expire_on_commit=False) as session:
        yield session
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_amap_settings_are_masked_preserved_and_cleared(db_session: Session) -> None:
    settings = update_settings(
        db_session,
        SettingsUpdate(
            amap_enabled=True,
            amap_js_key=" public-js-key ",
            amap_security_js_code=" private-security-code ",
        ),
    )
    public = settings_to_read(db_session, settings)

    assert settings.amap_js_key == "public-js-key"
    assert settings.amap_security_js_code == "private-security-code"
    assert public.amap_enabled is True
    assert public.amap_js_key == "public-js-key"
    assert public.has_amap_security_js_code is True
    assert public.amap_security_js_code_masked != "private-security-code"
    assert "amap_security_js_code" not in public.model_dump()
    assert "amap_source_coordinate_system" not in public.model_dump()

    preserved = update_settings(
        db_session,
        SettingsUpdate(amap_security_js_code=""),
    )
    assert preserved.amap_security_js_code == "private-security-code"

    cleared = update_settings(
        db_session,
        SettingsUpdate(clear_amap_security_js_code=True),
    )
    assert cleared.amap_security_js_code is None
    assert cleared.amap_enabled is False


def test_enabling_amap_requires_both_credentials(db_session: Session) -> None:
    with pytest.raises(ValueError, match="完整配置"):
        update_settings(db_session, SettingsUpdate(amap_enabled=True))
    db_session.rollback()

    settings = get_or_create_settings(db_session)
    assert settings.amap_enabled is False


def test_map_config_and_proxy_inject_server_secret_without_leaking_it(
    api_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "server-only-security-code"
    update_settings(
        api_session,
        SettingsUpdate(
            amap_enabled=True,
            amap_js_key="browser-visible-key",
            amap_security_js_code=secret,
        ),
    )
    captured: dict[str, object] = {}
    upstream_response = FakeUpstreamResponse()

    def fake_get(url: str, **kwargs: object) -> FakeUpstreamResponse:
        captured["url"] = url
        captured.update(kwargs)
        return upstream_response

    monkeypatch.setattr(amap_proxy.requests, "get", fake_get)
    app.dependency_overrides[get_db] = lambda: api_session
    try:
        client = TestClient(app)
        config = client.get("/api/map/config")
        proxied = client.get(
            "/_AMapService/v3/geocode/regeo",
            params={
                "key": "browser-visible-key",
                "location": "118.1,25.1",
                "jscode": "attacker",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert config.status_code == 200
    assert config.json() == {
        "enabled": True,
        "js_key": "browser-visible-key",
        "jitter": 0.00005,
        "service_host": "/_AMapService",
    }
    assert secret not in config.text
    assert proxied.status_code == 200
    assert proxied.json() == {"status": "1"}
    assert secret not in proxied.text
    assert captured["url"] == "https://restapi.amap.com/v3/geocode/regeo"
    params = captured["params"]
    assert isinstance(params, list)
    assert ("jscode", "attacker") not in params
    assert ("jscode", secret) in params
    assert captured["allow_redirects"] is False
    assert upstream_response.closed is True


def test_amap_proxy_rejects_unlisted_paths_before_network_access(
    api_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    update_settings(
        api_session,
        SettingsUpdate(
            amap_enabled=True,
            amap_js_key="browser-visible-key",
            amap_security_js_code="server-only-security-code",
        ),
    )
    called = False

    def unexpected_get(*args: object, **kwargs: object) -> FakeUpstreamResponse:
        nonlocal called
        called = True
        return FakeUpstreamResponse()

    monkeypatch.setattr(amap_proxy.requests, "get", unexpected_get)
    app.dependency_overrides[get_db] = lambda: api_session
    try:
        response = TestClient(app).get("/_AMapService/v3/direction/driving")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "AMAP_PATH_NOT_ALLOWED"
    assert called is False


def test_amap_proxy_maps_network_errors_without_echoing_secret(
    api_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "never-echo-this-security-code"
    update_settings(
        api_session,
        SettingsUpdate(
            amap_enabled=True,
            amap_js_key="browser-visible-key",
            amap_security_js_code=secret,
        ),
    )

    def failed_get(*args: object, **kwargs: object) -> FakeUpstreamResponse:
        raise requests.Timeout(f"timeout with {secret}")

    monkeypatch.setattr(amap_proxy.requests, "get", failed_get)
    app.dependency_overrides[get_db] = lambda: api_session
    try:
        response = TestClient(app).get(
            "/_AMapService/v3/assistant/coordinate/convert",
            params={"locations": "118.1,25.1", "coordsys": "gps"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    assert response.json()["detail"]["code"] == "AMAP_UPSTREAM_ERROR"
    assert secret not in response.text


def test_disabled_map_config_does_not_expose_stored_key(api_session: Session) -> None:
    settings = get_or_create_settings(api_session)
    settings.amap_enabled = False
    settings.amap_js_key = "stored-but-disabled"
    settings.amap_security_js_code = "stored-secret"
    api_session.commit()

    app.dependency_overrides[get_db] = lambda: api_session
    try:
        response = TestClient(app).get("/api/map/config")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["enabled"] is False
    assert response.json()["js_key"] is None
    assert "stored-secret" not in response.text
    assert "stored-but-disabled" not in response.text


def test_amap_proxy_enforces_response_size_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    upstream_response = FakeUpstreamResponse(b"x" * (amap_proxy.MAX_RESPONSE_BYTES + 1))
    monkeypatch.setattr(
        amap_proxy.requests,
        "get",
        lambda *args, **kwargs: upstream_response,
    )

    with pytest.raises(AmapResponseTooLarge):
        proxy_amap_request(
            "v3/geocode/regeo",
            [("location", "118.1,25.1")],
            "server-secret",
        )
    assert upstream_response.closed is True


def test_amap_access_log_filter_removes_coordinate_query_string() -> None:
    record = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=(
            "127.0.0.1:1234",
            "GET",
            "/_AMapService/v3/assistant/coordinate/convert?locations=118.1%2C25.1",
            "1.1",
            200,
        ),
        exc_info=None,
    )

    assert AmapAccessLogFilter().filter(record) is True
    assert isinstance(record.args, tuple)
    assert record.args[2] == "/_AMapService/v3/assistant/coordinate/convert"
