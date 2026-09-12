"""Pydantic request and response schemas."""

from __future__ import annotations

import base64
import binascii
import re
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ImageMode = Literal["single", "library", "latest"]
RunStatus = Literal["no_task", "success", "partial", "failed", "fatal"]
WorkerState = Literal[
    "unconfigured", "idle", "queued", "executing", "paused", "error", "stopping"
]
UserRole = Literal["admin", "user"]
UserStatus = Literal["profile_pending", "pending", "active", "rejected", "disabled"]


class SettingsRead(BaseModel):
    configured: bool
    version: int
    has_user_token: bool
    user_token_masked: str | None
    jitter: float
    heartbeat_interval: int
    task_keywords: list[str]
    image_mode: ImageMode
    selected_image_id: str | None
    worker_enabled: bool
    notification_enabled: bool


class SettingsUpdate(BaseModel):
    user_token: str | None = None
    clear_user_token: bool = False
    jitter: float | None = Field(default=None, ge=0, le=0.001)
    heartbeat_interval: int | None = Field(default=None, ge=10, le=86400)
    task_keywords: list[str] | None = None
    image_mode: ImageMode | None = None
    selected_image_id: str | None = None
    worker_enabled: bool | None = None
    notification_enabled: bool | None = None

    @field_validator("user_token", mode="before")
    @classmethod
    def normalize_user_token(cls, value: object) -> object:
        """Accept a raw USER_TOKEN or extract it from a complete Authorization value."""
        if value is None or not isinstance(value, str):
            return value
        candidate = value.strip()
        if not candidate or candidate.startswith("2_"):
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

    @field_validator("task_keywords")
    @classmethod
    def validate_keywords(cls, value: list[str] | None) -> list[str] | None:
        return None if value is None else [item.strip() for item in value if item.strip()]

    @model_validator(mode="after")
    def validate_secret_actions(self) -> "SettingsUpdate":
        if self.clear_user_token and self.user_token:
            raise ValueError("不能同时设置并清除 Token")
        return self


class SystemSettingsRead(BaseModel):
    setup_state: Literal["uninitialized", "system_configured", "admin_binding", "initialized"]
    public_base_url: str | None
    menu_name: str
    wechat_app_id: str | None
    wechat_template_id: str | None
    wechat_enabled: bool
    has_wechat_app_secret: bool
    wechat_app_secret_masked: str | None
    amap_enabled: bool
    amap_js_key: str | None
    has_amap_security_js_code: bool
    amap_security_js_code_masked: str | None
    log_level: str
    menu_synced_at: datetime | None


class SystemSettingsUpdate(BaseModel):
    public_base_url: str | None = None
    menu_name: str | None = Field(default=None, min_length=1, max_length=32)
    wechat_app_id: str | None = None
    wechat_app_secret: str | None = None
    clear_wechat_app_secret: bool = False
    wechat_template_id: str | None = None
    wechat_enabled: bool | None = None
    amap_enabled: bool | None = None
    amap_js_key: str | None = None
    amap_security_js_code: str | None = None
    clear_amap_security_js_code: bool = False
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] | None = None

    @field_validator(
        "public_base_url",
        "menu_name",
        "wechat_app_id",
        "wechat_app_secret",
        "wechat_template_id",
        "amap_js_key",
        "amap_security_js_code",
    )
    @classmethod
    def trim_strings(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("public_base_url")
    @classmethod
    def validate_public_url(cls, value: str | None) -> str | None:
        if value is not None and value and not value.startswith("https://"):
            raise ValueError("公网地址必须使用 HTTPS")
        return value.rstrip("/") if value else value


class BootstrapSystemRequest(BaseModel):
    wechat_app_id: str = Field(min_length=1)
    wechat_app_secret: str = Field(min_length=1)
    wechat_template_id: str = Field(min_length=1)
    public_base_url: str
    menu_name: str = Field(default="签到管理", min_length=1, max_length=32)
    amap_enabled: bool = False
    amap_js_key: str | None = None
    amap_security_js_code: str | None = None
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"

    @field_validator(
        "wechat_app_id", "wechat_app_secret", "wechat_template_id",
        "public_base_url", "menu_name", "amap_js_key", "amap_security_js_code",
    )
    @classmethod
    def strip_values(cls, value: str | None) -> str | None:
        return value.strip() if value is not None else None

    @field_validator("public_base_url")
    @classmethod
    def require_https(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("公网地址必须使用 HTTPS")
        return value.rstrip("/")

    @model_validator(mode="after")
    def validate_amap(self) -> "BootstrapSystemRequest":
        if self.amap_enabled and not (self.amap_js_key and self.amap_security_js_code):
            raise ValueError("启用高德地图前必须完整填写 JS Key 和 Security JS Code")
        return self


class BootstrapStatus(BaseModel):
    setup_state: Literal["uninitialized", "system_configured", "admin_binding", "initialized"]
    initialized: bool
    system_configured: bool
    admin_binding: bool
    requires_system_configuration: bool


class PairingRead(BaseModel):
    id: str
    kind: Literal["admin", "login"]
    status: str
    auth_url: str | None = None
    expires_at: datetime
    user_status: str | None = None


class ProfileUpdate(BaseModel):
    nickname: str = Field(min_length=1, max_length=64)


class AuthUserRead(BaseModel):
    id: str
    nickname: str | None
    avatar_url: str | None
    role: UserRole
    status: UserStatus
    rejection_reason: str | None
    csrf_token: str | None = None


class SessionRead(BaseModel):
    id: str
    device_type: str
    user_agent: str
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    current: bool


class UserAdminRead(BaseModel):
    id: str
    openid: str
    unionid: str | None
    nickname: str | None
    avatar_url: str | None
    role: UserRole
    status: UserStatus
    rejection_reason: str | None
    configured: bool
    worker_enabled: bool
    last_login_at: datetime | None
    created_at: datetime


class UserPage(BaseModel):
    items: list[UserAdminRead]
    total: int
    page: int
    page_size: int


class UserAdminUpdate(BaseModel):
    status: Literal["pending", "active", "rejected", "disabled"] | None = None
    role: UserRole | None = None
    rejection_reason: str | None = Field(default=None, max_length=500)


class AuditLogRead(BaseModel):
    id: int
    actor_user_id: str | None
    target_user_id: str | None
    action: str
    result: str
    detail: str | None
    created_at: datetime


class AuditPage(BaseModel):
    items: list[AuditLogRead]
    total: int
    page: int
    page_size: int


class MapConfigRead(BaseModel):
    enabled: bool
    js_key: str | None
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
    job_id: str | None = None


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
    setup_state: str = "uninitialized"


class LogEntry(BaseModel):
    timestamp: str
    level: str
    logger: str | None = None
    message: str


class LogPage(BaseModel):
    entries: list[LogEntry]
    next_cursor: int | None
    reset: bool