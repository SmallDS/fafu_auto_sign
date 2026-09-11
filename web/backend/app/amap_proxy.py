"""Restricted proxy for AMap Web service calls."""

from __future__ import annotations

from collections.abc import Iterable
import logging

import requests
from fastapi.responses import Response

AMAP_SERVICE_BASE = "https://restapi.amap.com"
ALLOWED_PATHS = {
    "v3/geocode/regeo",
    "v3/assistant/coordinate/convert",
}
CONNECT_TIMEOUT_SECONDS = 3
READ_TIMEOUT_SECONDS = 8
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class AmapProxyError(Exception):
    """Base error for safe AMap proxy failures."""


class UnsupportedAmapPath(AmapProxyError):
    """Raised when a request targets a service outside the allowlist."""


class AmapResponseTooLarge(AmapProxyError):
    """Raised when the upstream response exceeds the configured limit."""


class AmapUpstreamUnavailable(AmapProxyError):
    """Raised when AMap cannot be reached."""


class AmapAccessLogFilter(logging.Filter):
    """Remove coordinate-bearing query strings from AMap access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and len(record.args) >= 3:
            request_target = record.args[2]
            if isinstance(request_target, str) and request_target.startswith("/_AMapService/"):
                args = list(record.args)
                args[2] = request_target.split("?", 1)[0]
                record.args = tuple(args)
        return True


def install_amap_access_log_filter() -> None:
    """Install the redaction filter once on Uvicorn's access logger."""
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, AmapAccessLogFilter) for item in access_logger.filters):
        access_logger.addFilter(AmapAccessLogFilter())


def proxy_amap_request(
    service_path: str,
    query_items: Iterable[tuple[str, str]],
    security_js_code: str,
) -> Response:
    """Forward one allowlisted GET request without exposing the security code."""
    normalized = service_path.strip("/")
    if normalized not in ALLOWED_PATHS:
        raise UnsupportedAmapPath

    params = [(key, value) for key, value in query_items if key.lower() != "jscode"]
    params.append(("jscode", security_js_code))
    upstream = None
    try:
        upstream = requests.get(
            f"{AMAP_SERVICE_BASE}/{normalized}",
            params=params,
            timeout=(CONNECT_TIMEOUT_SECONDS, READ_TIMEOUT_SECONDS),
            allow_redirects=False,
            stream=True,
        )
        body_parts: list[bytes] = []
        total = 0
        for chunk in upstream.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > MAX_RESPONSE_BYTES:
                raise AmapResponseTooLarge
            body_parts.append(chunk)

        headers: dict[str, str] = {}
        for name in ("Content-Type", "Cache-Control"):
            value = upstream.headers.get(name)
            if value:
                headers[name] = value
        return Response(
            content=b"".join(body_parts),
            status_code=upstream.status_code,
            headers=headers,
        )
    except AmapProxyError:
        raise
    except requests.RequestException as exc:
        raise AmapUpstreamUnavailable from exc
    finally:
        if upstream is not None:
            upstream.close()
