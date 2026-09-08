"""Single-threaded scheduler for automatic sign runs."""

from __future__ import annotations

import json
import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select

from app.config_adapter import build_app_config
from app.database import SessionLocal
from app.errors import ConfigurationIncomplete
from app.models import Image, RunHistory
from app.repository import configuration_state, get_or_create_settings, image_path
from fafu_auto_sign.executor import SignExecutor

logger = logging.getLogger(__name__)


class WorkerManager:
    """Own a single background thread and serialize all sign attempts."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._manual_pending = False
        self._settings_changed = True
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
            if self._state == "executing" or self._manual_pending:
                return False
            with SessionLocal() as session:
                configured, _ = configuration_state(session)
            if not configured:
                return False
            self._manual_pending = True
            self._condition.notify_all()
            return True

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
                self._state = "executing"

            fatal = False
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
                payload = summary.to_dict()
                task_results = payload.get("task_results", [])
                error = summary.error
                status = summary.status
                fatal = status == "fatal"
                text = error or {
                    "no_task": "未发现待签到任务",
                    "success": "签到成功",
                    "partial": "部分任务处理失败",
                    "failed": "签到失败",
                    "fatal": "发生致命错误，调度已暂停",
                }.get(status, status)
                with SessionLocal() as session:
                    session.add(
                        RunHistory(
                            trigger=summary.trigger,
                            config_version=summary.config_version,
                            started_at=summary.started_at,
                            finished_at=summary.finished_at,
                            status=status,
                            discovered_count=summary.discovered_count,
                            success_count=summary.success_count,
                            failure_count=summary.failure_count,
                            summary=text,
                            task_details_json=json.dumps(
                                task_results, ensure_ascii=False, default=str
                            ),
                            error=error,
                        )
                    )
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
                logger.exception("后台签到执行失败")
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
                            error=str(exc),
                        )
                    )
                    session.commit()
                self._set_state("error")
            finally:
                finished = datetime.now(timezone.utc)
                with self._condition:
                    self._last_check_at = finished
                    self._next_check_at = finished + timedelta(seconds=interval)
                    last_version = version
                    if not self._stopping and self._state != "error":
                        self._state = "paused" if fatal else "idle"
