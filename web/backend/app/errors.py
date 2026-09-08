"""Application error types and consistent HTTP error payloads."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException


def api_error(
    status_code: int, code: str, message: str, fields: dict[str, str] | None = None
) -> HTTPException:
    """Build an HTTP exception using the public error envelope."""
    detail: dict[str, Any] = {"code": code, "message": message}
    if fields:
        detail["fields"] = fields
    return HTTPException(status_code=status_code, detail=detail)


class ConfigurationIncomplete(RuntimeError):
    """Raised when the stored configuration cannot execute a sign run."""
