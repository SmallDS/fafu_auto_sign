from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from fafu_auto_sign.services.wechat_test_account_service import (
    REQUEST_TIMEOUT,
    SEND_URL,
    TOKEN_URL,
    WeChatTestAccountError,
    WeChatTestAccountService,
)


class Response:
    def __init__(self, payload, http_error: bool = False):
        self.payload = payload
        self.http_error = http_error

    def raise_for_status(self):
        if self.http_error:
            raise requests.HTTPError("https://example.invalid/?secret=LEAK")

    def json(self):
        return self.payload


@pytest.fixture(autouse=True)
def clear_cache():
    WeChatTestAccountService.clear_cache()


def service(session):
    return WeChatTestAccountService("appid", "appsecret", "template", "openid", session=session)


def test_token_is_cached_and_expires_early():
    session = MagicMock()
    session.get.side_effect = [
        Response({"access_token": "token-1", "expires_in": 1000}),
        Response({"access_token": "token-2", "expires_in": 1000}),
    ]
    session.post.return_value = Response({"errcode": 0})
    sender = service(session)
    with patch("fafu_auto_sign.services.wechat_test_account_service.time.monotonic", side_effect=[100.0, 101.0, 801.0]):
        sender.send("标题", "内容")
        sender.send("标题", "内容")
        sender.send("标题", "内容")
    assert session.get.call_count == 2
    session.get.assert_any_call(
        TOKEN_URL,
        params={"grant_type": "client_credential", "appid": "appid", "secret": "appsecret"},
        timeout=REQUEST_TIMEOUT,
    )


def test_invalid_token_refreshes_once():
    session = MagicMock()
    session.get.side_effect = [
        Response({"access_token": "old", "expires_in": 7200}),
        Response({"access_token": "new", "expires_in": 7200}),
    ]
    session.post.side_effect = [Response({"errcode": 40014}), Response({"errcode": 0})]
    service(session).send("标题", "内容", "task-1", True)
    assert session.get.call_count == 2
    assert session.post.call_count == 2
    assert session.post.call_args_list[1].kwargs["params"] == {"access_token": "new"}


def test_fixed_template_payload_mapping():
    session = MagicMock()
    session.get.return_value = Response({"access_token": "token", "expires_in": 7200})
    session.post.return_value = Response({"errcode": 0})
    service(session).send("签到标题", "签到备注", "task-7", False)
    call = session.post.call_args
    assert call.args == (SEND_URL,)
    assert call.kwargs["timeout"] == REQUEST_TIMEOUT
    assert call.kwargs["params"] == {"access_token": "token"}
    assert call.kwargs["json"]["touser"] == "openid"
    assert call.kwargs["json"]["template_id"] == "template"
    data = call.kwargs["json"]["data"]
    assert data["first"] == {"value": "签到标题"}
    assert data["keyword1"] == {"value": "task-7"}
    assert data["keyword2"] == {"value": "失败"}
    assert data["remark"] == {"value": "签到备注"}
    assert data["keyword3"]["value"]


def test_network_error_is_sanitized():
    session = MagicMock()
    session.get.side_effect = requests.ConnectionError(
        "https://api.weixin.qq.com/cgi-bin/token?secret=appsecret&openid=openid"
    )
    with pytest.raises(WeChatTestAccountError) as caught:
        service(session).send("标题", "内容")
    message = str(caught.value)
    assert "appsecret" not in message
    assert "openid" not in message
    assert "http" not in message


def test_wechat_error_is_sanitized_and_not_retried_for_other_codes():
    session = MagicMock()
    session.get.return_value = Response({"access_token": "access-token", "expires_in": 7200})
    session.post.return_value = Response(
        {"errcode": 40003, "errmsg": "invalid openid:openid appsecret access-token"}
    )
    with pytest.raises(WeChatTestAccountError) as caught:
        service(session).send("标题", "内容")
    assert session.post.call_count == 1
    assert "openid" not in str(caught.value).lower()
    assert "appsecret" not in str(caught.value).lower()
    assert "access-token" not in str(caught.value).lower()