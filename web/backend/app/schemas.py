"""Pydantic request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

ImageMode = Literal["single", "library", "latest"]
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

    @field_validator("user_token")
    @classmethod
    def validate_user_token(cls, value: str | None) -> str | None:
        if value and not value.startswith("2_"):
            raise ValueError("必须以 2_ 开头")
        return value

    @field_validator("task_keywords")
    @classmethod
    def validate_keywords(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return value
        cleaned = [item.strip() for item in value if item.strip()]
        if not cleaned:
            raise ValueError("至少需要一个非空关键词")
        return cleaned

    @model_validator(mode="after")
    def validate_secret_actions(self) -> "SettingsUpdate":
        if self.clear_user_token and self.user_token:
            raise ValueError("不能同时设置并清除 Token")
        return self


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
