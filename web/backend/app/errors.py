"""Application error types and consistent HTTP error payloads."""

from __future__ import annotations

import re
from typing import Any

from fastapi import HTTPException
from requests.exceptions import RequestException
from sqlalchemy.exc import SQLAlchemyError

_SENSITIVE_ASSIGNMENT = re.compile(
    r"(?i)(authorization|user_token|serverchan(?:_key)?|sendkey|signimg|password|refresh_token|we_link_token|device_id|cookie)"
    r"[\"']?\s*[:=]\s*[\"']?([^\s,;&\"']+)"
)
_URL_QUERY = re.compile(r"(https?://[^\s?]+)\?[^\s]*", re.IGNORECASE)
_TOKEN = re.compile(r"\b2_[A-Za-z0-9._~+\-/=]+")
_SENDKEY = re.compile(r"\b(?:SCT|SC3|sctp)[A-Za-z0-9._~+\-/=]+", re.IGNORECASE)


def api_error(
    status_code: int, code: str, message: str, fields: dict[str, str] | None = None
) -> HTTPException:
    """Build an HTTP exception using the public error envelope."""
    detail: dict[str, Any] = {"code": code, "message": message}
    if fields:
        detail["fields"] = fields
    return HTTPException(status_code=status_code, detail=detail)


def redact_sensitive_text(value: str | None, fallback: str | None = None) -> str | None:
    """Redact secrets and URL queries before text reaches history or API output."""
    if not value:
        return fallback
    redacted = _URL_QUERY.sub(r"\1?[已隐藏]", value)
    redacted = _SENSITIVE_ASSIGNMENT.sub(r"\1=[已隐藏]", redacted)
    redacted = _TOKEN.sub("[Token已隐藏]", redacted)
    redacted = _SENDKEY.sub("[SendKey已隐藏]", redacted)
    return redacted


def redact_sensitive_payload(value: Any) -> Any:
    """Recursively redact strings before a structured payload is persisted."""
    if isinstance(value, str):
        return redact_sensitive_text(value)
    if isinstance(value, dict):
        return {key: redact_sensitive_payload(item) for key, item in value.items()}
    if isinstance(value, list):
        return [redact_sensitive_payload(item) for item in value]
    if isinstance(value, tuple):
        return [redact_sensitive_payload(item) for item in value]
    return value


def safe_exception_message(exc: BaseException, fallback: str = "执行异常") -> str:
    """Return a stable exception category without serializing exception details."""
    if isinstance(exc, SystemExit):
        return "FAFU 鉴权或时间校验失败"
    if isinstance(exc, RequestException):
        return "FAFU 网络请求失败"
    if isinstance(exc, SQLAlchemyError):
        return "数据库操作失败"
    return fallback


class ConfigurationIncomplete(RuntimeError):
    """Raised when the stored configuration cannot execute a sign run."""
