"""可被 CLI 与 Web Worker 共同调用的单轮签到执行器。"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Literal

from requests.exceptions import ConnectionError, RequestException

from fafu_auto_sign.client import FAFUClient
from fafu_auto_sign.config import AppConfig
from fafu_auto_sign.services import SignService, TaskService
from fafu_auto_sign.services.task_service import TaskDetailsFetchError
from fafu_auto_sign.services.upload_service import UploadService

TaskRunStatus = Literal["success", "failed", "skipped"]
RunStatus = Literal["no_task", "success", "partial", "failed", "fatal"]


def _utc_now() -> datetime:
    """返回带 UTC 时区信息的当前时间。"""
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class TaskRunResult:
    """单个签到任务的执行结果。"""

    task_id: str
    status: TaskRunStatus
    started_at: datetime
    finished_at: datetime
    position_name: str | None = None
    image_url: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """转换为适合 JSON/SQLite JSON 字段存储的字典。"""
        result = asdict(self)
        result["started_at"] = self.started_at.isoformat()
        result["finished_at"] = self.finished_at.isoformat()
        return result


@dataclass(frozen=True)
class RunSummary:
    """一次任务扫描和签到流程的汇总结果。"""

    trigger: str
    config_version: int
    status: RunStatus
    started_at: datetime
    finished_at: datetime
    task_results: tuple[TaskRunResult, ...] = ()
    error: str | None = None
    discovered_task_count: int = 0
    fatal_http_status: int | None = None

    @property
    def discovered_count(self) -> int:
        """本轮从任务列表中发现的任务数量。"""
        return self.discovered_task_count

    @property
    def success_count(self) -> int:
        """成功签到的任务数量。"""
        return sum(result.status == "success" for result in self.task_results)

    @property
    def failure_count(self) -> int:
        """处理失败的任务数量（跳过不计为请求失败）。"""
        return sum(result.status == "failed" for result in self.task_results)

    @property
    def skipped_count(self) -> int:
        """因缺少任务详情等原因跳过的任务数量。"""
        return sum(result.status == "skipped" for result in self.task_results)

    def to_dict(self) -> dict[str, Any]:
        """转换为适合 API 响应和持久化的字典。"""
        return {
            "trigger": self.trigger,
            "config_version": self.config_version,
            "status": self.status,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "task_results": [result.to_dict() for result in self.task_results],
            "error": self.error,
            "discovered_count": self.discovered_count,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "skipped_count": self.skipped_count,
        }


class SignExecutor:
    """执行单轮签到，并将业务结果聚合为稳定的数据结构。"""

    def __init__(
        self,
        config: AppConfig,
        *,
        client: FAFUClient | None = None,
        task_service: TaskService | None = None,
        upload_service: UploadService | None = None,
        sign_service: SignService | None = None,
    ) -> None:
        self.config = config
        self.client = client if client is not None else FAFUClient(config)
        self.task_service = (
            task_service if task_service is not None else TaskService(self.client, config)
        )
        self.upload_service = (
            upload_service if upload_service is not None else UploadService(self.client)
        )
        self.sign_service = (
            sign_service if sign_service is not None else SignService(self.client, config)
        )
        self.logger = logging.getLogger(self.__class__.__name__)
        self._closed = False

    def _process_task(
        self,
        task_id: str,
        should_stop: Callable[[], bool] | None = None,
        strict_details: bool = False,
        coordinate_override: tuple[float, float] | None = None,
    ) -> tuple[TaskRunResult | None, bool]:
        """执行共享的“详情→上传→签到”单任务调用链。"""
        task_started_at = _utc_now()
        position_name: str | None = None
        image_url: str | None = None
        try:
            self.logger.info(f"开始处理任务 {task_id}")
            task_details = (
                self.task_service.get_task_details_strict(int(task_id))
                if strict_details
                else self.task_service.get_task_details(int(task_id))
            )
            if task_details is None:
                error = "任务无地理位置限制或任务详情不可用"
                self.logger.warning(f"任务 {task_id} 无地理位置限制，跳过签到")
                return (
                    TaskRunResult(
                        task_id=task_id,
                        status="skipped",
                        started_at=task_started_at,
                        finished_at=_utc_now(),
                        error=error,
                    ),
                    False,
                )

            position_name = task_details.position_name
            self.logger.info(f"获取到签到位置：{position_name}")
            if should_stop is not None and should_stop():
                return None, True

            image_url = self.upload_service.upload_image(self.config.image_path)
            if not image_url:
                return (
                    TaskRunResult(
                        task_id=task_id,
                        status="failed",
                        started_at=task_started_at,
                        finished_at=_utc_now(),
                        position_name=position_name,
                        error="图片上传失败",
                    ),
                    False,
                )

            base_lng, base_lat = (
                coordinate_override
                if coordinate_override is not None
                else (task_details.base_lng, task_details.base_lat)
            )
            success = self.sign_service.submit_sign(
                task_id=int(task_id),
                position_id=task_details.position_id,
                base_lng=base_lng,
                base_lat=base_lat,
                image_url=image_url,
            )
            result_error: str | None
            if success:
                self.logger.info(f"✅ 签到成功！位置：{position_name}")
                status: TaskRunStatus = "success"
                result_error = None
            else:
                self.logger.error(f"❌ 签到失败！位置：{position_name}")
                status = "failed"
                result_error = "签到提交失败"
            return (
                TaskRunResult(
                    task_id=task_id,
                    status=status,
                    started_at=task_started_at,
                    finished_at=_utc_now(),
                    position_name=position_name,
                    image_url=image_url,
                    error=result_error,
                ),
                False,
            )
        except SystemExit:
            raise
        except TaskDetailsFetchError:
            raise
        except Exception as exc:
            self.logger.error(f"处理任务 {task_id} 时发生异常: {exc}")
            return (
                TaskRunResult(
                    task_id=task_id,
                    status="failed",
                    started_at=task_started_at,
                    finished_at=_utc_now(),
                    position_name=position_name,
                    image_url=image_url,
                    error=str(exc),
                ),
                False,
            )

    def execute_task_once(
        self,
        task_id: str,
        trigger: str = "manual",
        config_version: int = 0,
        capture_fatal: bool = False,
        coordinate_override: tuple[float, float] | None = None,
    ) -> RunSummary:
        """处理指定任务一次，不重新扫描任务列表。"""
        if self._closed:
            raise RuntimeError("SignExecutor 已关闭，不能继续执行")
        started_at = _utc_now()
        try:
            result, _ = self._process_task(
                str(task_id),
                strict_details=True,
                coordinate_override=coordinate_override,
            )
            task_results = (result,) if result is not None else ()
            result_list = list(task_results)
            return RunSummary(
                trigger=trigger,
                config_version=config_version,
                status=self._status_from_results(result_list),
                started_at=started_at,
                finished_at=_utc_now(),
                task_results=task_results,
                discovered_task_count=1,
                error=self._error_summary(result_list),
            )
        except TaskDetailsFetchError:
            raise
        except SystemExit as exc:
            if not capture_fatal:
                raise
            return self._fatal_summary(
                task_id=str(task_id),
                trigger=trigger,
                config_version=config_version,
                started_at=started_at,
                exit_code=exc.code,
                http_status=getattr(exc, "http_status", None),
                discovered_count=1,
            )
        except (ConnectionError, RequestException) as exc:
            error = f"请求错误: {exc}"
        except Exception as exc:
            error = f"发生异常: {exc}"
        self.logger.error(error)
        return RunSummary(
            trigger=trigger,
            config_version=config_version,
            status="failed",
            started_at=started_at,
            finished_at=_utc_now(),
            discovered_task_count=1,
            error=error,
        )

    def execute_once(
        self,
        trigger: str = "scheduled",
        config_version: int = 0,
        capture_fatal: bool = False,
        should_stop: Callable[[], bool] | None = None,
    ) -> RunSummary:
        """扫描并处理一次待签到任务。"""
        if self._closed:
            raise RuntimeError("SignExecutor 已关闭，不能继续执行")

        started_at = _utc_now()
        task_results: list[TaskRunResult] = []
        discovered_task_count = 0
        active_task_id: str | None = None
        stopped = False
        try:
            task_ids = self.task_service.get_pending_tasks()
            discovered_task_count = len(task_ids)
            if not task_ids:
                return RunSummary(
                    trigger=trigger,
                    config_version=config_version,
                    status="no_task",
                    started_at=started_at,
                    finished_at=_utc_now(),
                )

            self.logger.info(f"发现 {len(task_ids)} 个待签到任务")
            for raw_task_id in task_ids:
                if should_stop is not None and should_stop():
                    stopped = True
                    break
                active_task_id = str(raw_task_id)
                result, stopped = self._process_task(active_task_id, should_stop)
                if result is not None:
                    task_results.append(result)
                active_task_id = None
                if stopped:
                    break

            status: RunStatus
            if stopped:
                status = (
                    "partial"
                    if any(item.status == "success" for item in task_results)
                    else "failed"
                )
            else:
                status = self._status_from_results(task_results)
            error = self._error_summary(task_results)
            if stopped:
                error = "; ".join(part for part in (error, "执行已停止") if part)
            return RunSummary(
                trigger=trigger,
                config_version=config_version,
                status=status,
                started_at=started_at,
                finished_at=_utc_now(),
                task_results=tuple(task_results),
                discovered_task_count=discovered_task_count,
                error=error,
            )
        except TaskDetailsFetchError:
            raise
        except SystemExit as exc:
            if not capture_fatal:
                raise
            return self._fatal_summary(
                task_id=active_task_id,
                trigger=trigger,
                config_version=config_version,
                started_at=started_at,
                exit_code=exc.code,
                http_status=getattr(exc, "http_status", None),
                discovered_count=discovered_task_count,
                previous_results=task_results,
            )
        except ConnectionError as exc:
            error = f"网络连接错误: {exc}"
        except RequestException as exc:
            error = f"请求错误: {exc}"
        except Exception as exc:
            error = f"发生异常: {exc}"
        self.logger.error(error)
        return RunSummary(
            trigger=trigger,
            config_version=config_version,
            status="failed",
            started_at=started_at,
            finished_at=_utc_now(),
            task_results=tuple(task_results),
            discovered_task_count=discovered_task_count,
            error=error,
        )

    def _fatal_summary(
        self,
        *,
        task_id: str | None,
        trigger: str,
        config_version: int,
        started_at: datetime,
        exit_code: object,
        http_status: int | None,
        discovered_count: int,
        previous_results: list[TaskRunResult] | None = None,
    ) -> RunSummary:
        error = f"致命请求错误（退出码: {exit_code}）"
        results = list(previous_results or [])
        if task_id is not None:
            results.append(
                TaskRunResult(
                    task_id=task_id,
                    status="failed",
                    started_at=started_at,
                    finished_at=_utc_now(),
                    error=error,
                )
            )
        self.logger.error(error)
        return RunSummary(
            trigger=trigger,
            config_version=config_version,
            status="fatal",
            started_at=started_at,
            finished_at=_utc_now(),
            task_results=tuple(results),
            discovered_task_count=discovered_count,
            error=error,
            fatal_http_status=http_status,
        )

    @staticmethod
    def _status_from_results(task_results: list[TaskRunResult]) -> RunStatus:
        """根据任务级结果计算整轮状态。"""
        if task_results and all(result.status == "success" for result in task_results):
            return "success"
        if any(result.status == "success" for result in task_results):
            return "partial"
        return "failed"

    @staticmethod
    def _error_summary(task_results: list[TaskRunResult]) -> str | None:
        """汇总任务错误，供历史列表快速展示。"""
        errors = [result.error for result in task_results if result.error]
        return "; ".join(errors) if errors else None

    def close(self) -> None:
        """关闭底层 HTTP 会话；重复调用是安全的。"""
        if self._closed:
            return
        self.client.close()
        self._closed = True

    def __enter__(self) -> "SignExecutor":
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.close()
