from __future__ import annotations

from email.message import Message
from types import SimpleNamespace
from urllib.parse import quote
from urllib.request import Request

import pytest

import app.fafu_auth_transport as transport


def response(status: int, body: bytes) -> transport._Response:
    return transport._Response(
        status=status, body=body,
        url=transport.API_BASE + "/sign_in/student/my/page",
        headers=Message(),
    )


@pytest.mark.parametrize(
    ("status", "body", "expected"),
    [
        (200, b'{"records":[]}', "valid"),
        (200, b'{"message":"expired"}', "expired"),
        (401, b"", "expired"),
        (408, b"", "clock_error"),
        (503, b"", "unavailable"),
    ],
)
def test_token_validation_distinguishes_expiry_and_clock(
    monkeypatch, status: int, body: bytes, expected: str
) -> None:
    calls = []

    def fake_send(url, data=None, **kwargs):
        calls.append((url, data, kwargs))
        return response(status, body)

    monkeypatch.setattr(transport, "_send", fake_send)
    assert transport.FafuAuthTransport().validate_token("2_test") == expected
    assert calls[0][0] == transport.API_BASE + "/sign_in/student/my/page?rows=1&pageNum=1"
    assert calls[0][1] == b""
    assert calls[0][2]["headers"]["Authorization"]


def test_refresh_401_requires_reconnect_but_503_is_transient(monkeypatch) -> None:
    monkeypatch.setattr(transport, "_send", lambda *args, **kwargs: response(401, b"{}"))
    with pytest.raises(transport.FafuAuthTransportError) as invalid:
        transport.FafuAuthTransport().refresh_welink("refresh-secret")
    assert invalid.value.code == "INVALID_REFRESH"

    monkeypatch.setattr(transport, "_send", lambda *args, **kwargs: response(503, b"{}"))
    with pytest.raises(transport.FafuAuthTransportError) as transient:
        transport.FafuAuthTransport().refresh_welink("refresh-secret")
    assert transient.value.code == "UPSTREAM_UNAVAILABLE"


def test_cross_host_redirect_drops_cas_cookie() -> None:
    source = Request(
        transport.CAS_BASE + "/login",
        headers={"Cookie": "CASTGC=secret", "Authorization": "secret", "Referer": "secret"},
    )
    redirected = transport._RestrictedRedirect().redirect_request(
        source, None, 302, "Found", {},
        "https://api.welink.huaweicloud.com/sso/oauth2/magcallback.html?code=test",
    )
    assert redirected is not None
    assert redirected.get_header("Cookie") is None
    assert redirected.get_header("Authorization") is None
    assert redirected.get_header("Referer") is None


def test_cas_service_is_passed_to_sms_and_mfa_without_welink_host_restriction(
    monkeypatch,
) -> None:
    auth_url = transport.CAS_BASE + "/oauth2.0/authorize?client_id=test"
    service = "https://auth.fafu.edu.cn/authserver/return"
    login_url = transport.CAS_BASE + "/reAuthCheck/reAuthLoginView.do?service=" + quote(service, safe="")
    calls = []

    def reply(url: str, body: bytes) -> transport._Response:
        return transport._Response(200, body, url, Message())

    def fake_send(url, data=None, **kwargs):
        if url.endswith("/enterprise/auth/info"):
            return reply(url, ('{"data":{"thirdLoginUrl":"' + auth_url + '"}}').encode())
        assert url.endswith("/v7/callback/LoginReg")
        return reply(url, b'{"refresh_token":"refresh-token"}')

    def fake_cas(url, data=None, **kwargs):
        calls.append((url, data))
        if url == auth_url:
            return reply(url, b'<input name="pwdEncryptSalt" value="salt">')
        if "/checkNeedCaptcha.htl?" in url:
            return reply(url, b'{"isNeed":false}')
        if url == transport.CAS_BASE + "/login":
            return reply(login_url, b"")
        if url.endswith("/dynamicCode/getDynamicCodeByReauth.do"):
            return reply(url, b'{"res":"success"}')
        if url.endswith("/reAuthCheck/reAuthSubmit.do"):
            return reply(url, b"reAuth_success")
        if url.startswith(transport.CAS_BASE + "/login?service="):
            return reply(transport.MAG_BASE + "/callback?code=oauth-code", b"")
        raise AssertionError(url)

    monkeypatch.setattr(transport, "_send", fake_send)
    monkeypatch.setattr(transport, "_cas", fake_cas)
    monkeypatch.setattr(transport, "_aes_cbc", lambda *args: "encrypted")
    monkeypatch.setattr(transport, "_cookie_token", lambda headers: "welink-token")
    monkeypatch.setattr(transport, "_rsa_tenant", lambda: "tenant")
    monkeypatch.setattr(transport.http.cookiejar, "CookieJar", lambda: [
        SimpleNamespace(domain="auth.fafu.edu.cn", name="CASTGC", value="cas-cookie")
    ])
    monkeypatch.setattr(transport.urllib.request, "build_opener", lambda *args: object())
    client = transport.FafuAuthTransport()
    monkeypatch.setattr(client, "exchange_welink", lambda token, device: "2_fafu-token")

    assert client.begin("student", "password") == (service, "CASTGC=cas-cookie")
    assert any(url.endswith("/dynamicCode/getDynamicCodeByReauth.do") for url, _ in calls)
    assert client.complete(service, "CASTGC=cas-cookie", "123456", "device") == (
        "welink-token", "refresh-token", "2_fafu-token"
    )
    assert any(url.endswith("/reAuthCheck/reAuthSubmit.do") for url, _ in calls)
