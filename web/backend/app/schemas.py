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
    notification_enabled: bool
    has_serverchan_key: bool
    serverchan_key_masked: str | None
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
    notification_enabled: bool | None = None
    serverchan_key: str | None = None
    clear_serverchan_key: bool = False
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

    @field_validator("serverchan_key")
    @classmethod
    def validate_sendkey(cls, value: str | None) -> str | None:
        if value and not value.startswith(("SCT", "SC3", "sctp")):
            raise ValueError("必须以 SCT、SC3 或 sctp 开头")
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
        if self.clear_serverchan_key and self.serverchan_key:
            raise ValueError("不能同时设置并清除 SendKey")
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
