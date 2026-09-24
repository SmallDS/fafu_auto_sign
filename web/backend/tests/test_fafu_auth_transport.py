from __future__ import annotations

from email.message import Message
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
