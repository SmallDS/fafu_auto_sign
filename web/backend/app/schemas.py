"""Pydantic request and response schemas."""

from __future__ import annotations

import base64
import binascii
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ImageMode = Literal["single", "library", "latest"]
AmapCoordinateSystem = Literal["gcj02", "wgs84"]
RunStatus = Literal["no_task", "success", "partial", "failed", "fatal"]
WorkerState = Literal["unconfigured", "idle", "executing", "paused", "error", "stopping"]


class SettingsRead(BaseModel):
    configured: bool
    version: int
    has_user_token: bool
    user_token_masked: str | None
    jitter: float
    heartbeat_interval: int
    log_level: str
    amap_enabled: bool
    amap_js_key: str | None
    has_amap_security_js_code: bool
    amap_security_js_code_masked: str | None
    amap_source_coordinate_system: AmapCoordinateSystem
    wechat_test_enabled: bool
    wechat_test_app_id: str | None
    wechat_test_template_id: str | None
    has_wechat_test_app_secret: bool
    wechat_test_app_secret_masked: str | None
    has_wechat_test_openid: bool
    wechat_test_openid_masked: str | None
    task_keywords: list[str]
    image_mode: ImageMode
    selected_image_id: str | None
    worker_enabled: bool


class SettingsUpdate(BaseModel):
    user_token: str | None = None
    clear_user_token: bool = False
    jitter: float | None = Field(default=None, ge=0, le=0.001)
    heartbeat_interval: int | None = Field(default=None, ge=10, le=86400)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] | None = None
    amap_enabled: bool | None = None
    amap_js_key: str | None = None
    amap_security_js_code: str | None = None
    clear_amap_security_js_code: bool = False
    amap_source_coordinate_system: AmapCoordinateSystem | None = None
    wechat_test_enabled: bool | None = None
    wechat_test_app_id: str | None = None
    wechat_test_app_secret: str | None = None
    clear_wechat_test_app_secret: bool = False
    wechat_test_template_id: str | None = None
    wechat_test_openid: str | None = None
    clear_wechat_test_openid: bool = False
    task_keywords: list[str] | None = None
    image_mode: ImageMode | None = None
    selected_image_id: str | None = None
    worker_enabled: bool | None = None

    @field_validator("user_token", mode="before")
    @classmethod
    def normalize_user_token(cls, value: object) -> object:
        """Accept a raw USER_TOKEN or extract it from a full Authorization value."""
        if value is None or not isinstance(value, str):
            return value
        candidate = value.strip()
        if not candidate:
            return candidate
        if candidate.startswith("2_"):
            return candidate

        message = "请输入以 2_ 开头的用户 Token，或有效的完整 Base64 Authorization"
        try:
            decoded_bytes = base64.b64decode(candidate, validate=True)
            if base64.b64encode(decoded_bytes).decode("ascii") != candidate:
                raise ValueError(message)
            decoded = decoded_bytes.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError, ValueError) as exc:
            raise ValueError(message) from exc

        parts = decoded.split(":")
        if (
            len(parts) != 4
            or not parts[0].isdigit()
            or re.fullmatch(r"[A-Za-z0-9]{16}", parts[1]) is None
            or re.fullmatch(r"[0-9a-fA-F]{32}", parts[2]) is None
            or not parts[3].startswith("2_")
            or len(parts[3]) <= 2
        ):
            raise ValueError(message)
        return parts[3]

    @field_validator("amap_js_key", "amap_security_js_code")
    @classmethod
    def trim_amap_credentials(cls, value: str | None) -> str | None:
        if value is None:
            return value
        return value.strip()

    @field_validator("task_keywords")
    @classmethod
    def validate_keywords(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        return [item.strip() for item in value if item.strip()]

    @model_validator(mode="after")
    def validate_secret_actions(self) -> "SettingsUpdate":
        if self.clear_user_token and self.user_token:
            raise ValueError("不能同时设置并清除 Token")
        if self.clear_amap_security_js_code and self.amap_security_js_code:
            raise ValueError("不能同时设置并清除高德 Security JS Code")
        return self


class MapConfigRead(BaseModel):
    enabled: bool
    js_key: str | None
    source_coordinate_system: AmapCoordinateSystem
    jitter: float
    service_host: str = "/_AMapService"


class ImageRead(BaseModel):
    id: str
    category: Literal["library", "latest"]
    original_name: str
    mime_type: str
    size: int
    sha256: str
    created_at: datetime


class ImagePage(BaseModel):
    items: list[ImageRead]
    total: int
    page: int
    page_size: int


class RunRead(BaseModel):
    id: int
    trigger: Literal["scheduled", "manual"]
    config_version: int
    started_at: datetime
    finished_at: datetime | None
    result: RunStatus
    task_count: int
    success_count: int
    failure_count: int
    summary: str | None
    details: list[dict[str, object]] | dict[str, object] | None


class RunPage(BaseModel):
    items: list[RunRead]
    total: int
    page: int
    page_size: int


class SignTaskRead(BaseModel):
    id: str
    name: str
    begin_time: int
    end_time: int


class SignTaskPage(BaseModel):
    items: list[SignTaskRead]
    total: int | None
    page: int
    page_size: int
    has_more: bool


class SignTaskDetailsRead(BaseModel):
    task_id: int
    position_id: int
    base_lng: float
    base_lat: float
    position_name: str


class SignTaskSubmit(BaseModel):
    source_page: int = Field(ge=1)
    page_size: int = Field(ge=1, le=100)


class WorkerActionResponse(BaseModel):
    state: WorkerState
    message: str


class StatusResponse(BaseModel):
    configured: bool
    worker_state: WorkerState
    last_check_at: datetime | None
    next_check_at: datetime | None
    last_error: str | None
    recent_run: RunRead | None
    stats_7d: dict[str, int]


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    database: Literal["ok"] = "ok"
    worker_state: WorkerState
    configured: bool


class LogEntry(BaseModel):
    timestamp: str
    level: str
    logger: str | None = None
    message: str


class LogPage(BaseModel):
    entries: list[LogEntry]
    next_cursor: int | None
    reset: bool
