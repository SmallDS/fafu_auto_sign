"""WeChat Official Account test-account template notifications."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, ClassVar

import requests

TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
SEND_URL = "https://api.weixin.qq.com/cgi-bin/message/template/send"
REQUEST_TIMEOUT = 10
INVALID_TOKEN_CODES = {40014, 42001}


class WeChatTestAccountError(RuntimeError):
    """A stable, secret-free error suitable for logs and API boundaries."""


@dataclass(frozen=True)
class _TokenEntry:
    value: str
    valid_until: float


class WeChatTestAccountService:
    """Send fixed-shape template messages through a WeChat test account."""

    _token_cache: ClassVar[dict[tuple[str, str], _TokenEntry]] = {}
    _cache_lock: ClassVar[threading.Lock] = threading.Lock()

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        template_id: str,
        openid: str,
        *,
        session: Any | None = None,
    ) -> None:
        self.app_id = app_id
        self.app_secret = app_secret
        self.template_id = template_id
        self.openid = openid
        self.session = session or requests.Session()

    @classmethod
    def clear_cache(cls) -> None:
        """Clear the in-memory token cache (primarily useful for tests)."""
        with cls._cache_lock:
            cls._token_cache.clear()

    def _invalidate_token(self) -> None:
        with self._cache_lock:
            self._token_cache.pop((self.app_id, self.app_secret), None)

    @staticmethod
    def _json(response: Any, operation: str) -> dict[str, Any]:
        try:
            payload = response.json()
        except (TypeError, ValueError) as exc:
            raise WeChatTestAccountError(f"微信测试号{operation}响应格式无效") from exc
        if not isinstance(payload, dict):
            raise WeChatTestAccountError(f"微信测试号{operation}响应格式无效")
        return payload

    def _get_token(self) -> str:
        key = (self.app_id, self.app_secret)
        now = time.monotonic()
        with self._cache_lock:
            cached = self._token_cache.get(key)
            if cached and cached.valid_until > now:
                return cached.value
            try:
                response = self.session.get(
                    TOKEN_URL,
                    params={
                        "grant_type": "client_credential",
                        "appid": self.app_id,
                        "secret": self.app_secret,
                    },
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                payload = self._json(response, "令牌")
            except WeChatTestAccountError:
                raise
            except requests.RequestException as exc:
                raise WeChatTestAccountError("微信测试号令牌请求失败") from exc
            errcode = payload.get("errcode")
            token = payload.get("access_token")
            if errcode not in (None, 0) or not isinstance(token, str) or not token:
                raise WeChatTestAccountError("微信测试号令牌获取失败")
            expires_in = payload.get("expires_in", 7200)
            ttl = int(expires_in) if isinstance(expires_in, (int, float)) else 7200
            self._token_cache[key] = _TokenEntry(token, now + max(0, ttl - 300))
            return token

    def _payload(
        self,
        title: str,
        content: str,
        task_id: str | None,
        success: bool | None,
    ) -> dict[str, Any]:
        status = "成功" if success is True else "失败" if success is False else "通知"
        return {
            "touser": self.openid,
            "template_id": self.template_id,
            "data": {
                "first": {"value": title},
                "keyword1": {"value": task_id or "—"},
                "keyword2": {"value": status},
                "keyword3": {"value": datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")},
                "remark": {"value": content},
            },
        }

    def send(
        self,
        title: str,
        content: str,
        task_id: str | None = None,
        success: bool | None = None,
    ) -> None:
        """Send a message, refreshing an invalid token at most once."""
        payload = self._payload(title, content, task_id, success)
        for attempt in range(2):
            token = self._get_token()
            try:
                response = self.session.post(
                    SEND_URL,
                    params={"access_token": token},
                    json=payload,
                    timeout=REQUEST_TIMEOUT,
                )
                response.raise_for_status()
                result = self._json(response, "消息")
            except WeChatTestAccountError:
                raise
            except requests.RequestException as exc:
                raise WeChatTestAccountError("微信测试号消息请求失败") from exc
            errcode = result.get("errcode", 0)
            if errcode == 0:
                return
            if errcode in INVALID_TOKEN_CODES and attempt == 0:
                self._invalidate_token()
                continue
            raise WeChatTestAccountError("微信测试号消息发送失败")
        raise WeChatTestAccountError("微信测试号消息发送失败")
