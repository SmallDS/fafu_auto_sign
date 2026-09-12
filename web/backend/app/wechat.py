"""WeChat OAuth, global token validation and menu synchronization."""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

import requests

OAUTH_AUTHORIZE_URL = "https://open.weixin.qq.com/connect/oauth2/authorize"
OAUTH_TOKEN_URL = "https://api.weixin.qq.com/sns/oauth2/access_token"
OAUTH_USERINFO_URL = "https://api.weixin.qq.com/sns/userinfo"
GLOBAL_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
MENU_CREATE_URL = "https://api.weixin.qq.com/cgi-bin/menu/create"
TIMEOUT = (5, 10)


class WeChatError(RuntimeError):
    """Secret-free WeChat integration failure."""


def _json(response: requests.Response, operation: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise WeChatError(f"微信{operation}请求失败") from exc
    if not isinstance(payload, dict) or payload.get("errcode") not in (None, 0):
        raise WeChatError(f"微信{operation}失败")
    return payload


def get_global_access_token(app_id: str, app_secret: str) -> str:
    try:
        response = requests.get(
            GLOBAL_TOKEN_URL,
            params={"grant_type": "client_credential", "appid": app_id, "secret": app_secret},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise WeChatError("微信测试号凭据验证失败") from exc
    payload = _json(response, "测试号凭据验证")
    token = payload.get("access_token")
    if not isinstance(token, str) or not token:
        raise WeChatError("微信测试号凭据验证失败")
    return token


def build_oauth_url(
    app_id: str,
    redirect_uri: str,
    state: str,
    scope: str,
) -> str:
    query = urlencode(
        {
            "appid": app_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": scope,
            "state": state,
        }
    )
    return f"{OAUTH_AUTHORIZE_URL}?{query}#wechat_redirect"


def exchange_oauth_code(app_id: str, app_secret: str, code: str) -> dict[str, Any]:
    try:
        response = requests.get(
            OAUTH_TOKEN_URL,
            params={
                "appid": app_id,
                "secret": app_secret,
                "code": code,
                "grant_type": "authorization_code",
            },
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise WeChatError("微信网页授权失败") from exc
    payload = _json(response, "网页授权")
    if not payload.get("openid") or not payload.get("access_token"):
        raise WeChatError("微信网页授权返回信息不完整")
    return payload


def fetch_oauth_profile(access_token: str, openid: str) -> dict[str, Any]:
    try:
        response = requests.get(
            OAUTH_USERINFO_URL,
            params={"access_token": access_token, "openid": openid, "lang": "zh_CN"},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise WeChatError("微信用户资料读取失败") from exc
    return _json(response, "用户资料读取")


def sync_menu(
    app_id: str,
    app_secret: str,
    public_base_url: str,
    menu_name: str,
) -> None:
    token = get_global_access_token(app_id, app_secret)
    target = f"{public_base_url.rstrip('/')}/auth/wechat/start?next=/dashboard"
    try:
        response = requests.post(
            MENU_CREATE_URL,
            params={"access_token": token},
            json={"button": [{"type": "view", "name": menu_name, "url": target}]},
            timeout=TIMEOUT,
        )
    except requests.RequestException as exc:
        raise WeChatError("微信公众号菜单同步失败") from exc
    _json(response, "菜单同步")