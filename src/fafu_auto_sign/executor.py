"""可被 CLI 与 Web Worker 共同调用的单轮签到执行器。"""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from collections.abc import Callable
from typing import Any, Literal

from requests.exceptions import ConnectionError, RequestException

from fafu_auto_sign.client import FAFUClient
from fafu_auto_sign.config import AppConfig
from fafu_auto_sign.services import SignService, TaskService
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
    """执行单轮签到，并将业务结果聚合为稳定的数据结构。

    ``config`` 在构造时即被视为本轮配置快照。默认情况下执行器拥有
    自己的客户端；测试或 CLI 兼容层也可以注入已创建的服务实例。
    """

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

    def execute_once(
        self,
        trigger: str = "scheduled",
        config_version: int = 0,
        capture_fatal: bool = False,
        should_stop: Callable[[], bool] | None = None,
    ) -> RunSummary:
        """扫描并处理一次待签到任务。

        ``capture_fatal`` 为 ``True`` 时，将底层客户端针对 401/408 抛出的
        ``SystemExit`` 转换为 ``fatal`` 结果，供 Web Worker 自动暂停。
        CLI 使用默认值 ``False``，保持原有致命退出行为。
        """
        if self._closed:
            raise RuntimeError("SignExecutor 已关闭，不能继续执行")

        started_at = _utc_now()
        task_results: list[TaskRunResult] = []
        discovered_task_count = 0
        active_task_id: str | None = None
        active_task_started_at: datetime | None = None
        active_position_name: str | None = None
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
                    discovered_task_count=0,
                )

            self.logger.info(f"发现 {len(task_ids)} 个待签到任务")

            for raw_task_id in task_ids:
                if should_stop is not None and should_stop():
                    stopped = True
                    break
                active_task_id = str(raw_task_id)
                active_task_started_at = _utc_now()
                active_position_name = None
                image_url: str | None = None

                try:
                    self.logger.info(f"开始处理任务 {active_task_id}")
                    task_details = self.task_service.get_task_details(int(active_task_id))
                    if task_details is None:
                        skip_error = "任务无地理位置限制或任务详情不可用"
                        self.logger.warning(f"任务 {active_task_id} 无地理位置限制，跳过签到")
                        task_results.append(
                            TaskRunResult(
                                task_id=active_task_id,
                                status="skipped",
                                started_at=active_task_started_at,
                                finished_at=_utc_now(),
                                error=skip_error,
                            )
                        )
                        active_task_id = None
                        continue

                    active_position_name = task_details.position_name
                    self.logger.info(f"获取到签到位置：{active_position_name}")

                    if should_stop is not None and should_stop():
                        stopped = True
                        break
                    image_url = self.upload_service.upload_image(self.config.image_path)
                    if not image_url:
                        task_results.append(
                            TaskRunResult(
                                task_id=active_task_id,
                                status="failed",
                                started_at=active_task_started_at,
                                finished_at=_utc_now(),
                                position_name=active_position_name,
                                error="图片上传失败",
                            )
                        )
                        active_task_id = None
                        continue

                    success = self.sign_service.submit_sign(
                        task_id=int(active_task_id),
                        position_id=task_details.position_id,
                        base_lng=task_details.base_lng,
                        base_lat=task_details.base_lat,
                        image_url=image_url,
                    )
                    if success:
                        self.logger.info(f"✅ 签到成功！位置：{active_position_name}")
                        task_status: TaskRunStatus = "success"
                        task_error: str | None = None
                    else:
                        self.logger.error(f"❌ 签到失败！位置：{active_position_name}")
                        task_status = "failed"
                        task_error = "签到提交失败"

                    task_results.append(
                        TaskRunResult(
                            task_id=active_task_id,
                            status=task_status,
                            started_at=active_task_started_at,
                            finished_at=_utc_now(),
                            position_name=active_position_name,
                            image_url=image_url,
                            error=task_error,
                        )
                    )
                    active_task_id = None
                except SystemExit:
                    raise
                except Exception as exc:
                    error = f"处理任务 {active_task_id} 时发生异常: {exc}"
                    self.logger.error(error)
                    task_results.append(
                        TaskRunResult(
                            task_id=active_task_id or str(raw_task_id),
                            status="failed",
                            started_at=active_task_started_at,
                            finished_at=_utc_now(),
                            position_name=active_position_name,
                            image_url=image_url,
                            error=str(exc),
                        )
                    )
                    active_task_id = None

            run_status: RunStatus
            if stopped:
                run_status = (
                    "partial"
                    if any(result.status == "success" for result in task_results)
                    else "failed"
                )
            else:
                run_status = self._status_from_results(task_results)
            run_error = self._error_summary(task_results)
            if stopped:
                run_error = "; ".join(part for part in (run_error, "执行已停止") if part)
            return RunSummary(
                trigger=trigger,
                config_version=config_version,
                status=run_status,
                started_at=started_at,
                finished_at=_utc_now(),
                task_results=tuple(task_results),
                discovered_task_count=discovered_task_count,
                error=run_error,
            )
        except SystemExit as exc:
            if not capture_fatal:
                raise

            fatal_error = f"致命请求错误（退出码: {exc.code}）"
            if active_task_id is not None and active_task_started_at is not None:
                task_results.append(
                    TaskRunResult(
                        task_id=active_task_id,
                        status="failed",
                        started_at=active_task_started_at,
                        finished_at=_utc_now(),
                        position_name=active_position_name,
                        error=fatal_error,
                    )
                )
            self.logger.error(fatal_error)
            return RunSummary(
                trigger=trigger,
                config_version=config_version,
                status="fatal",
                started_at=started_at,
                finished_at=_utc_now(),
                task_results=tuple(task_results),
                discovered_task_count=discovered_task_count,
                error=fatal_error,
            )
        except ConnectionError as exc:
            error = f"网络连接错误: {exc}"
            self.logger.error(error)
        except RequestException as exc:
            error = f"请求错误: {exc}"
            self.logger.error(error)
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
