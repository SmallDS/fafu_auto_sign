"""WeChat OAuth, global token validation and menu synchronization."""

from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

import requests

OAUTH_AUTHORIZE_URL = "https://open.weixin.qq.com/connect/oauth2/authorize"
OAUTH_TOKEN_URL = "https://api.weixin.qq.com/sns/oauth2/access_token"
OAUTH_USERINFO_URL = "https://api.weixin.qq.com/sns/userinfo"
GLOBAL_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
MENU_CREATE_URL = "https://api.weixin.qq.com/cgi-bin/menu/create"
TIMEOUT = (5, 10)
WECHAT_ERROR_MESSAGES = {
    "10003": "网页授权回调域名与微信后台配置不一致",
    "40001": "AppSecret 或 access token 无效",
    "40013": "AppID 无效",
    "40016": "菜单按钮数量或结构不符合要求",
    "40018": "菜单名称长度不符合要求",
    "40125": "AppSecret 无效",
    "40164": "服务器出口 IP 未加入微信接口 IP 白名单",
    "42001": "access token 已过期，请重试",
    "45009": "微信接口调用已达到频率限制",
    "48001": "当前测试号没有该接口权限",
}


class WeChatError(RuntimeError):
    """Secret-free WeChat integration failure."""


def normalize_wechat_text(value: object) -> str:
    """Normalize profile text and repair common UTF-8-as-Latin-1 mojibake."""
    text = str(value).strip()
    if not text:
        return ""
    try:
        repaired = text.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return text
    def latin1_noise(candidate: str) -> int:
        return sum(1 for character in candidate if 0x80 <= ord(character) <= 0xFF)

    return repaired if repaired != text and latin1_noise(repaired) < latin1_noise(text) else text


def _json(response: requests.Response, operation: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
        payload = json.loads(response.content.decode("utf-8-sig"))
    except (requests.RequestException, UnicodeDecodeError, ValueError) as exc:
        raise WeChatError(f"微信{operation}请求失败") from exc
    if not isinstance(payload, dict):
        raise WeChatError(f"微信{operation}返回了无效数据")
    error_code = payload.get("errcode")
    if error_code not in (None, 0, "0"):
        code = str(error_code)
        reason = WECHAT_ERROR_MESSAGES.get(code, "微信接口拒绝了请求")
        raise WeChatError(f"微信{operation}失败（错误码 {code}）：{reason}")
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
    target = (
        f"{public_base_url.rstrip('/')}/auth/wechat/start?"
        + urlencode({"next": "/dashboard"})
    )
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