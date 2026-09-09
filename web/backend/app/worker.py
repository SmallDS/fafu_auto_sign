"""Single-threaded scheduler for automatic sign runs."""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import select

from app.config_adapter import build_app_config
from app.database import SessionLocal
from app.errors import ConfigurationIncomplete, safe_exception_message
from app.models import Image, RunHistory
from app.repository import (
    configuration_state,
    get_or_create_settings,
    image_path,
    save_run_summary,
)
from fafu_auto_sign.executor import SignExecutor
from fafu_auto_sign.services.notification_service import NotificationService

logger = logging.getLogger(__name__)
ExecutionOwner = Literal["worker", "external"]


class WorkerManager:
    """Own a single background thread and serialize all sign attempts."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._manual_pending = False
        self._settings_changed = True
        self._execution_owner: ExecutionOwner | None = None
        self._state = "unconfigured"
        self._last_check_at: datetime | None = None
        self._next_check_at: datetime | None = None

    def start(self) -> None:
        with self._condition:
            if self._thread and self._thread.is_alive():
                return
            self._stopping = False
            self._thread = threading.Thread(target=self._run_loop, name="fafu-worker", daemon=False)
            self._thread.start()

    def stop(self, timeout: float = 290.0) -> None:
        with self._condition:
            self._stopping = True
            self._state = "stopping"
            self._condition.notify_all()
        if self._thread:
            self._thread.join(timeout=timeout)

    def notify_configuration_changed(self) -> None:
        with self._condition:
            self._settings_changed = True
            self._condition.notify_all()

    def request_run_now(self) -> bool:
        with self._condition:
            if self._execution_owner is not None or self._manual_pending or self._stopping:
                return False
            with SessionLocal() as session:
                configured, _ = configuration_state(session)
            if not configured:
                return False
            self._manual_pending = True
            self._condition.notify_all()
            return True

    def try_begin_external_execution(self) -> bool:
        """Reserve the shared execution slot for a direct manual submission."""
        with self._condition:
            if self._execution_owner is not None or self._manual_pending or self._stopping:
                return False
            self._execution_owner = "external"
            self._state = "executing"
            return True

    def finish_external_execution(self, *, configured: bool, worker_enabled: bool) -> None:
        """Release a manual execution slot and restore the scheduler state."""
        with self._condition:
            if self._execution_owner == "external":
                self._execution_owner = None
            if not self._stopping:
                self._state = (
                    "unconfigured" if not configured else "idle" if worker_enabled else "paused"
                )
            self._condition.notify_all()

    def snapshot(self) -> dict[str, Any]:
        with self._condition:
            return {
                "state": self._state,
                "last_check_at": self._last_check_at,
                "next_check_at": self._next_check_at,
            }

    def _is_stopping(self) -> bool:
        with self._condition:
            return self._stopping

    def _set_state(self, state: str) -> None:
        with self._condition:
            self._state = state

    def _run_loop(self) -> None:
        last_version: int | None = None
        while True:
            with self._condition:
                if self._stopping:
                    return
            with SessionLocal() as session:
                settings = get_or_create_settings(session)
                configured, _ = configuration_state(session, settings)
                enabled = settings.worker_enabled
                version = settings.config_version
                interval = settings.heartbeat_interval

            with self._condition:
                if self._execution_owner == "external":
                    self._condition.wait(timeout=1.0)
                    continue
                manual = self._manual_pending
                changed = self._settings_changed or last_version != version
                now = datetime.now(timezone.utc)
                due = self._next_check_at is None or now >= self._next_check_at
                if not configured:
                    self._state = "unconfigured"
                elif not enabled and not manual:
                    self._state = "paused"
                elif self._state != "error":
                    self._state = "idle"
                should_run = configured and (manual or (enabled and (changed or due)))
                if not should_run:
                    self._settings_changed = False
                    wait_seconds = 60.0
                    if enabled and self._next_check_at is not None:
                        wait_seconds = max(
                            0.1, min(60.0, (self._next_check_at - now).total_seconds())
                        )
                    self._condition.wait(timeout=wait_seconds)
                    continue
                trigger = "manual" if manual else "scheduled"
                self._manual_pending = False
                self._settings_changed = False
                self._execution_owner = "worker"
                self._state = "executing"

            fatal = False
            config = None
            try:
                with SessionLocal() as session:
                    settings = get_or_create_settings(session)
                    version = settings.config_version
                    interval = settings.heartbeat_interval
                    config = build_app_config(session, settings)
                with SignExecutor(config) as executor:
                    summary = executor.execute_once(
                        trigger=trigger,
                        config_version=version,
                        capture_fatal=True,
                        should_stop=self._is_stopping,
                    )
                fatal = summary.status == "fatal"
                NotificationService(config).notify_summary(summary)
                with SessionLocal() as session:
                    save_run_summary(session, summary)
                    if fatal:
                        settings = get_or_create_settings(session)
                        settings.worker_enabled = False
                    missing_latest = session.scalars(
                        select(Image).where(Image.purpose == "latest")
                    ).all()
                    for image in missing_latest:
                        if not image_path(image).exists():
                            session.delete(image)
                    session.commit()
            except ConfigurationIncomplete as exc:
                logger.warning("调度配置不完整: %s", exc)
            except Exception as exc:
                logger.error("后台签到执行失败")
                if config is not None:
                    NotificationService(config).notify(
                        "FAFU 签到失败", "后台执行异常", success=False
                    )
                now = datetime.now(timezone.utc)
                with SessionLocal() as session:
                    session.add(
                        RunHistory(
                            trigger=trigger,
                            config_version=version,
                            started_at=now,
                            finished_at=now,
                            status="failed",
                            summary="后台执行异常",
                            task_details_json="[]",
                            error=safe_exception_message(exc, "后台执行异常"),
                        )
                    )
                    session.commit()
                self._set_state("error")
            finally:
                finished = datetime.now(timezone.utc)
                enabled_after = False
                configured_after = False
                try:
                    with SessionLocal() as session:
                        current = get_or_create_settings(session)
                        enabled_after = current.worker_enabled
                        configured_after, _ = configuration_state(session, current)
                except Exception:
                    logger.error("后台执行结束后无法读取调度状态")
                with self._condition:
                    self._execution_owner = None
                    self._last_check_at = finished
                    self._next_check_at = finished + timedelta(seconds=interval)
                    last_version = version
                    if not self._stopping and self._state != "error":
                        self._state = (
                            "unconfigured"
                            if not configured_after
                            else "paused" if fatal or not enabled_after else "idle"
                        )
                    self._condition.notify_all()
