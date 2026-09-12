"""Persistent global single-thread scheduler for all users."""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import select

from app.config_adapter import build_app_config
from app.database import SessionLocal
from app.errors import ConfigurationIncomplete, safe_exception_message
from app.models import Image, RunHistory, Settings, SignJob, SystemSettings, User, utcnow
from app.repository import configuration_state, image_path, save_run_summary
from fafu_auto_sign.executor import SignExecutor
from fafu_auto_sign.services.notification_service import NotificationService

logger = logging.getLogger(__name__)
ExecutionOwner = Literal["worker", "external"]


def _aware(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class WorkerManager:
    """Own one execution slot and a restart-safe SQLite job queue."""

    def __init__(self) -> None:
        self._condition = threading.Condition()
        self._thread: threading.Thread | None = None
        self._stopping = False
        self._execution_owner: ExecutionOwner | None = None
        self._external_user_id: str | None = None
        self._active_user_id: str | None = None
        self._state = "unconfigured"

    def start(self) -> None:
        with self._condition:
            if self._thread and self._thread.is_alive():
                return
            self._stopping = False
            with SessionLocal() as session:
                for row in session.scalars(
                    select(SignJob).where(SignJob.status == "running")
                ):
                    row.status = "queued"
                    row.started_at = None
                session.commit()
            self._thread = threading.Thread(
                target=self._run_loop, name="fafu-worker", daemon=False
            )
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
            self._condition.notify_all()

    def enqueue_run(self, user_id: str, kind: str = "manual") -> str | None:
        with SessionLocal() as session:
            duplicate = session.scalar(
                select(SignJob).where(
                    SignJob.user_id == user_id,
                    SignJob.status.in_(("queued", "running")),
                )
            )
            if duplicate is not None:
                return None
            settings = session.scalar(
                select(Settings).where(Settings.user_id == user_id)
            )
            user = session.get(User, user_id)
            if settings is None or user is None or user.status != "active":
                return None
            configured, _ = configuration_state(session, settings)
            if not configured:
                return None
            row = SignJob(
                id=str(uuid.uuid4()),
                user_id=user_id,
                kind=kind,
                priority=10 if kind == "manual" else 20,
                status="queued",
            )
            session.add(row)
            session.commit()
        with self._condition:
            self._state = "queued"
            self._condition.notify_all()
        return row.id

    def request_run_now(self) -> bool:
        """Compatibility helper for the legacy single-user unit boundary."""
        with self._condition:
            return self._execution_owner is None and not self._stopping

    def try_begin_external_execution(self, user_id: str | None = None) -> bool:
        with self._condition:
            if self._execution_owner is not None or self._stopping:
                return False
            self._execution_owner = "external"
            self._external_user_id = user_id
            self._active_user_id = user_id
            self._state = "executing"
            return True

    def finish_external_execution(
        self,
        *,
        configured: bool,
        worker_enabled: bool,
        user_id: str | None = None,
    ) -> None:
        with self._condition:
            if self._execution_owner == "external":
                self._execution_owner = None
            self._external_user_id = None
            self._active_user_id = None
            if not self._stopping:
                self._state = (
                    "unconfigured"
                    if not configured
                    else "idle"
                    if worker_enabled
                    else "paused"
                )
            self._condition.notify_all()

    def snapshot(self, user_id: str | None = None) -> dict[str, Any]:
        with self._condition:
            executing = self._execution_owner is not None and (
                user_id is None or self._active_user_id == user_id
            )
            current_state = "executing" if executing else self._state
        last_check = None
        next_check = None
        if user_id:
            with SessionLocal() as session:
                settings = session.scalar(
                    select(Settings).where(Settings.user_id == user_id)
                )
                latest = session.scalar(
                    select(RunHistory)
                    .where(RunHistory.user_id == user_id)
                    .order_by(RunHistory.started_at.desc())
                    .limit(1)
                )
                queued = session.scalar(
                    select(SignJob).where(
                        SignJob.user_id == user_id,
                        SignJob.status == "queued",
                    )
                )
                if latest:
                    last_check = latest.finished_at
                if settings:
                    next_check = settings.next_run_at
                    configured, _ = configuration_state(session, settings)
                    if not executing:
                        if queued:
                            current_state = "queued"
                        elif not configured:
                            current_state = "unconfigured"
                        elif not settings.worker_enabled:
                            current_state = "paused"
                        else:
                            current_state = "idle"
        return {
            "state": current_state,
            "last_check_at": last_check,
            "next_check_at": next_check,
        }

    def _is_stopping(self) -> bool:
        with self._condition:
            return self._stopping

    def _schedule_due_users(self, session) -> None:
        system = session.get(SystemSettings, 1)
        if system is None or system.setup_state != "initialized":
            return
        now = utcnow()
        rows = session.execute(
            select(User, Settings)
            .join(Settings, Settings.user_id == User.id)
            .where(User.status == "active", Settings.worker_enabled.is_(True))
        ).all()
        for user, settings in rows:
            configured, _ = configuration_state(session, settings)
            due = settings.next_run_at is None or (_aware(settings.next_run_at) or now) <= now
            if not configured or not due:
                continue
            duplicate = session.scalar(
                select(SignJob).where(
                    SignJob.user_id == user.id,
                    SignJob.status.in_(("queued", "running")),
                )
            )
            if duplicate is None:
                session.add(
                    SignJob(
                        id=str(uuid.uuid4()),
                        user_id=user.id,
                        kind="scheduled",
                        priority=20,
                        status="queued",
                    )
                )
                settings.next_run_at = now + timedelta(seconds=settings.heartbeat_interval)
        session.commit()

    @staticmethod
    def _claim_next(session) -> SignJob | None:
        row = session.scalar(
            select(SignJob)
            .where(SignJob.status == "queued")
            .order_by(SignJob.priority.asc(), SignJob.created_at.asc())
            .limit(1)
        )
        if row:
            row.status = "running"
            row.started_at = utcnow()
            session.commit()
            session.refresh(row)
        return row

    def _run_loop(self) -> None:
        while True:
            with self._condition:
                if self._stopping:
                    return
                if self._execution_owner == "external":
                    self._condition.wait(timeout=1)
                    continue
            with SessionLocal() as session:
                self._schedule_due_users(session)
                job = self._claim_next(session)
            if job is None:
                with self._condition:
                    self._state = "idle"
                    self._condition.wait(timeout=5)
                continue

            with self._condition:
                self._execution_owner = "worker"
                self._active_user_id = job.user_id
                self._state = "executing"
            self._execute_job(job.id)
            with self._condition:
                self._execution_owner = None
                self._active_user_id = None
                if not self._stopping:
                    self._state = "idle"
                self._condition.notify_all()

    def _execute_job(self, job_id: str) -> None:
        config = None
        user_id = None
        try:
            with SessionLocal() as session:
                job = session.get(SignJob, job_id)
                if job is None:
                    return
                user_id = job.user_id
                user = session.get(User, user_id)
                settings = session.scalar(
                    select(Settings).where(Settings.user_id == user_id)
                )
                system = session.get(SystemSettings, 1)
                if (
                    user is None
                    or settings is None
                    or system is None
                    or user.status != "active"
                ):
                    raise ConfigurationIncomplete("用户不可调度")
                version = settings.config_version
                interval = settings.heartbeat_interval
                config = build_app_config(session, settings, system, user)
            trigger = "manual" if job.kind == "manual" else "scheduled"
            with SignExecutor(config) as executor:
                summary = executor.execute_once(
                    trigger=trigger,
                    config_version=version,
                    capture_fatal=True,
                    should_stop=self._is_stopping,
                )
            NotificationService(config).notify_summary(summary)
            with SessionLocal() as session:
                save_run_summary(session, summary, user_id)
                settings = session.scalar(
                    select(Settings).where(Settings.user_id == user_id)
                )
                current_job = session.get(SignJob, job_id)
                if summary.status == "fatal" and settings:
                    settings.worker_enabled = False
                if settings:
                    settings.next_run_at = utcnow() + timedelta(seconds=interval)
                for image in session.scalars(
                    select(Image).where(
                        Image.user_id == user_id, Image.purpose == "latest"
                    )
                ):
                    if not image_path(image).exists():
                        session.delete(image)
                if current_job:
                    current_job.status = "completed"
                    current_job.finished_at = utcnow()
                session.commit()
        except ConfigurationIncomplete as exc:
            logger.warning("用户调度配置不完整")
            self._finish_failed_job(job_id, str(exc), create_history=False)
        except Exception as exc:
            logger.error("后台签到执行失败")
            if config is not None:
                NotificationService(config).notify(
                    "FAFU 签到失败", "后台执行异常", success=False
                )
            self._finish_failed_job(
                job_id,
                safe_exception_message(exc, "后台执行异常"),
                create_history=True,
                user_id=user_id,
            )

    @staticmethod
    def _finish_failed_job(
        job_id: str,
        error: str,
        *,
        create_history: bool,
        user_id: str | None = None,
    ) -> None:
        now = utcnow()
        with SessionLocal() as session:
            job = session.get(SignJob, job_id)
            if job:
                job.status = "failed"
                job.finished_at = now
                job.error = safe_exception_message(RuntimeError(error), "后台执行异常")
            if create_history and user_id:
                settings = session.scalar(
                    select(Settings).where(Settings.user_id == user_id)
                )
                session.add(
                    RunHistory(
                        user_id=user_id,
                        trigger="manual" if job and job.kind == "manual" else "scheduled",
                        config_version=settings.config_version if settings else 0,
                        started_at=job.started_at if job and job.started_at else now,
                        finished_at=now,
                        status="failed",
                        summary="后台执行异常",
                        task_details_json="[]",
                        error="后台执行异常",
                    )
                )
            session.commit()