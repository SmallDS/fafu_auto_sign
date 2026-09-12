"""FAFU task browsing and serialized direct manual submission service."""

from __future__ import annotations

import time
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config_adapter import build_app_config, build_task_query_config
from app.errors import safe_exception_message
from app.models import RunHistory, User
from app.repository import (
    configuration_state,
    get_or_create_settings,
    get_or_create_system_settings,
    save_run_summary,
)
from app.worker import WorkerManager
from fafu_auto_sign.client import FAFUClient
from fafu_auto_sign.executor import RunStatus, RunSummary, SignExecutor, TaskRunResult
from fafu_auto_sign.services.notification_service import NotificationService
from fafu_auto_sign.services.task_service import (
    SignTaskPage,
    TaskDetails,
    TaskDetailsFetchError,
    TaskService,
)


class UpstreamUnavailable(RuntimeError):
    def __init__(self, run_id: int | None = None) -> None:
        super().__init__("FAFU 服务暂时不可用")
        self.run_id = run_id


class TaskDetailsUnavailable(RuntimeError):
    pass


class TaskNoLongerActive(RuntimeError):
    def __init__(self, run_id: int) -> None:
        super().__init__("任务已失效或不在签到时间内")
        self.run_id = run_id


class ExecutionBusy(RuntimeError):
    pass


def _user_settings(session: Session, user_id: str | None):
    return (
        get_or_create_settings(session, user_id)
        if user_id is not None
        else get_or_create_settings(session)
    )


class ManualSignService:
    """Coordinate all direct FAFU calls through the global execution slot."""

    def __init__(self, worker: WorkerManager) -> None:
        self.worker = worker

    def _acquire_slot(self, user_id: str | None) -> None:
        if not self.worker.try_begin_external_execution(user_id):
            raise ExecutionBusy("已有 FAFU 操作正在执行")

    @staticmethod
    def _disable_worker(session: Session, user_id: str | None) -> None:
        try:
            session.rollback()
            settings = _user_settings(session, user_id)
            settings.worker_enabled = False
            session.commit()
        except Exception:
            session.rollback()

    def _release_slot(self, session: Session, user_id: str | None) -> None:
        configured = False
        worker_enabled = False
        try:
            session.rollback()
            current = _user_settings(session, user_id)
            configured, _ = configuration_state(session, current)
            worker_enabled = current.worker_enabled
        except Exception:
            session.rollback()
        finally:
            self.worker.finish_external_execution(
                configured=configured,
                worker_enabled=worker_enabled,
                user_id=user_id,
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
        return RunSummary(
            trigger="manual",
            config_version=version,
            status=status,
            started_at=started_at,
            finished_at=finished_at,
            task_results=(
                TaskRunResult(
                    task_id=str(task_id),
                    status="failed",
                    started_at=started_at,
                    finished_at=finished_at,
                    error=error,
                ),
            ),
            error=error,
            discovered_task_count=1,
        )

    def list_tasks(
        self, session: Session, page: int, page_size: int, user_id: str | None = None
    ) -> SignTaskPage:
        settings = _user_settings(session, user_id)
        config = build_task_query_config(settings)
        self._acquire_slot(user_id)
        try:
            try:
                with FAFUClient(config) as client:
                    return TaskService(client, config).get_pending_task_page(page, page_size)
            except SystemExit as exc:
                self._disable_worker(session, user_id)
                raise UpstreamUnavailable() from exc
            except Exception as exc:
                raise UpstreamUnavailable() from exc
        finally:
            self._release_slot(session, user_id)

    def get_details(
        self, session: Session, task_id: int, user_id: str | None = None
    ) -> TaskDetails:
        settings = _user_settings(session, user_id)
        config = build_task_query_config(settings)
        self._acquire_slot(user_id)
        try:
            try:
                with FAFUClient(config) as client:
                    details = TaskService(client, config).get_task_details_strict(task_id)
            except SystemExit as exc:
                self._disable_worker(session, user_id)
                raise UpstreamUnavailable() from exc
            except TaskDetailsFetchError as exc:
                raise UpstreamUnavailable() from exc
            except Exception as exc:
                raise UpstreamUnavailable() from exc
            if details is None:
                raise TaskDetailsUnavailable("任务详情不可用")
            return details
        finally:
            self._release_slot(session, user_id)

    def submit(
        self,
        session: Session,
        task_id: int,
        source_page: int,
        page_size: int,
        user_id: str | None = None,
    ) -> RunHistory:
        settings = _user_settings(session, user_id)
        user = session.get(User, user_id) if user_id else None
        system = get_or_create_system_settings(session) if user else None
        config = build_app_config(session, settings, system, user)
        version = settings.config_version
        started_at = datetime.now(timezone.utc)
        self._acquire_slot(user_id)
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
                    task_id=task_id, version=version, status="fatal",
                    error=error, started_at=started_at,
                )
                row = save_run_summary(session, attempt, user_id)
                NotificationService(config).notify_summary(attempt)
                self._disable_worker(session, user_id)
                raise UpstreamUnavailable(row.id) from exc
            except Exception as exc:
                error = safe_exception_message(exc, "FAFU 请求失败")
                attempt = self._attempt_summary(
                    task_id=task_id, version=version, status="failed",
                    error=error, started_at=started_at,
                )
                row = save_run_summary(session, attempt, user_id)
                NotificationService(config).notify_summary(attempt)
                raise UpstreamUnavailable(row.id) from exc

            if inactive:
                attempt = self._attempt_summary(
                    task_id=task_id, version=version, status="failed",
                    error="任务已失效或不在签到时间内", started_at=started_at,
                )
                row = save_run_summary(session, attempt, user_id)
                NotificationService(config).notify_summary(attempt)
                raise TaskNoLongerActive(row.id)
            if summary is None:
                raise RuntimeError("单任务执行未产生结果")

            row = save_run_summary(session, summary, user_id)
            NotificationService(config).notify_summary(summary)
            if summary.status == "fatal":
                self._disable_worker(session, user_id)
                raise UpstreamUnavailable(row.id)
            return row
        finally:
            self._release_slot(session, user_id)