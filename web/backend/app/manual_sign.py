"""FAFU task browsing and serialized direct manual submission service."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config_adapter import build_app_config, build_task_query_config
from app.errors import safe_exception_message
from app.models import RunHistory
from app.repository import configuration_state, get_or_create_settings, save_run_summary
from app.worker import WorkerManager
from fafu_auto_sign.client import FAFUClient
from fafu_auto_sign.executor import RunStatus, RunSummary, TaskRunResult
from fafu_auto_sign.executor import SignExecutor
from fafu_auto_sign.services.notification_service import NotificationService
from fafu_auto_sign.services.task_service import (
    SignTaskPage,
    TaskDetails,
    TaskDetailsFetchError,
    TaskService,
)


class UpstreamUnavailable(RuntimeError):
    """Raised when FAFU cannot safely provide the requested data."""

    def __init__(self, run_id: int | None = None) -> None:
        super().__init__("FAFU 服务暂时不可用")
        self.run_id = run_id


class TaskDetailsUnavailable(RuntimeError):
    """Raised when a task has no usable location details."""


class TaskNoLongerActive(RuntimeError):
    """Raised when a selected task is missing or outside its active window."""

    def __init__(self, run_id: int) -> None:
        super().__init__("任务已失效或不在签到时间内")
        self.run_id = run_id


class ExecutionBusy(RuntimeError):
    """Raised when another FAFU operation owns the shared slot."""


class ManualSignService:
    """Coordinate serialized task reads and one-task manual sign runs."""

    def __init__(self, worker: WorkerManager) -> None:
        self.worker = worker

    def _acquire_slot(self) -> None:
        if not self.worker.try_begin_external_execution():
            raise ExecutionBusy("已有 FAFU 操作正在执行")

    def _disable_worker(self, session: Session) -> None:
        """Best-effort pause after a fatal upstream response."""
        try:
            session.rollback()
            settings = get_or_create_settings(session)
            settings.worker_enabled = False
            session.commit()
        except Exception:
            try:
                session.rollback()
            except Exception:
                pass

    def _release_slot(self, session: Session) -> None:
        """Always release the execution slot even if database state recovery fails."""
        configured = False
        worker_enabled = False
        try:
            session.rollback()
            current = get_or_create_settings(session)
            configured, _ = configuration_state(session, current)
            worker_enabled = current.worker_enabled
        except Exception:
            try:
                session.rollback()
            except Exception:
                pass
        finally:
            self.worker.finish_external_execution(
                configured=configured,
                worker_enabled=worker_enabled,
            )

    @staticmethod
    def _attempt_summary(
        *,
        task_id: int,
        version: int,
        status: RunStatus,
        error: str,
        started_at: datetime,
    ) -> RunSummary:
        finished_at = datetime.now(timezone.utc)
        task_result = TaskRunResult(
            task_id=str(task_id),
            status="failed",
            started_at=started_at,
            finished_at=finished_at,
            error=error,
        )
        return RunSummary(
            trigger="manual",
            config_version=version,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            task_results=(task_result,),
            error=error,
            discovered_task_count=1,
        )

    def list_tasks(self, session: Session, page: int, page_size: int) -> SignTaskPage:
        settings = get_or_create_settings(session)
        config = build_task_query_config(settings)
        self._acquire_slot()
        try:
            try:
                with FAFUClient(config) as client:
                    return TaskService(client, config).get_pending_task_page(page, page_size)
            except SystemExit as exc:
                self._disable_worker(session)
                raise UpstreamUnavailable() from exc
            except Exception as exc:
                raise UpstreamUnavailable() from exc
        finally:
            self._release_slot(session)

    def get_details(self, session: Session, task_id: int) -> TaskDetails:
        settings = get_or_create_settings(session)
        config = build_task_query_config(settings)
        self._acquire_slot()
        try:
            try:
                with FAFUClient(config) as client:
                    details = TaskService(client, config).get_task_details_strict(task_id)
            except SystemExit as exc:
                self._disable_worker(session)
                raise UpstreamUnavailable() from exc
            except TaskDetailsFetchError as exc:
                raise UpstreamUnavailable() from exc
            except Exception as exc:
                raise UpstreamUnavailable() from exc
            if details is None:
                raise TaskDetailsUnavailable("任务详情不可用")
            return details
        finally:
            self._release_slot(session)

    def submit(
        self,
        session: Session,
        task_id: int,
        source_page: int,
        page_size: int,
    ) -> RunHistory:
        settings = get_or_create_settings(session)
        config = build_app_config(session, settings)
        version = settings.config_version
        started_at = datetime.now(timezone.utc)
        self._acquire_slot()
        try:
            inactive = False
            summary: RunSummary | None = None
            try:
                with SignExecutor(config) as executor:
                    page = executor.task_service.get_pending_task_page(source_page, page_size)
                    task = next((item for item in page.items if item.id == str(task_id)), None)
                    now_ms = int(time.time() * 1000)
                    inactive = task is None or not task.begin_time <= now_ms <= task.end_time
                    if not inactive:
                        summary = executor.execute_task_once(
                            str(task_id),
                            trigger="manual",
                            config_version=version,
                            capture_fatal=True,
                        )
            except SystemExit as exc:
                error = safe_exception_message(exc)
                attempt = self._attempt_summary(
                    task_id=task_id,
                    version=version,
                    status="fatal",
                    error=error,
                    started_at=started_at,
                )
                row = save_run_summary(session, attempt)
                NotificationService(config).notify_summary(attempt)
                self._disable_worker(session)
                raise UpstreamUnavailable(row.id) from exc
            except Exception as exc:
                error = safe_exception_message(exc, "FAFU 请求失败")
                attempt = self._attempt_summary(
                    task_id=task_id,
                    version=version,
                    status="failed",
                    error=error,
                    started_at=started_at,
                )
                row = save_run_summary(session, attempt)
                NotificationService(config).notify_summary(attempt)
                raise UpstreamUnavailable(row.id) from exc

            if inactive:
                attempt = self._attempt_summary(
                    task_id=task_id,
                    version=version,
                    status="failed",
                    error="任务已失效或不在签到时间内",
                    started_at=started_at,
                )
                row = save_run_summary(session, attempt)
                NotificationService(config).notify_summary(attempt)
                raise TaskNoLongerActive(row.id)
            if summary is None:
                raise RuntimeError("单任务执行未产生结果")

            row = save_run_summary(session, summary)
            NotificationService(config).notify_summary(summary)
            if summary.status == "fatal":
                self._disable_worker(session)
                raise UpstreamUnavailable(row.id)
            return row
        finally:
            self._release_slot(session)
