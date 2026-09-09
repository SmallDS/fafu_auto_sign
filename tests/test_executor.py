"""共享单轮签到执行器测试。"""

from unittest.mock import MagicMock, patch

import pytest

from fafu_auto_sign.config import AppConfig
from fafu_auto_sign.executor import SignExecutor
from fafu_auto_sign.services.task_service import TaskDetails, TaskDetailsFetchError


def create_config(**overrides: object) -> AppConfig:
    values: dict[str, object] = {
        "user_token": "2_executor_test_token",
        "image_path": "test.jpg",
        "heartbeat_interval": 37,
    }
    values.update(overrides)
    return AppConfig(**values)


def create_executor(
    *,
    task_ids: list[str],
    details: TaskDetails | None = None,
    image_url: str | None = "http://qiniu.example/image.jpg",
    sign_success: bool = True,
) -> tuple[SignExecutor, MagicMock, MagicMock, MagicMock, MagicMock]:
    config = create_config()
    client = MagicMock()
    task_service = MagicMock()
    upload_service = MagicMock()
    sign_service = MagicMock()
    task_service.get_pending_tasks.return_value = task_ids
    task_service.get_task_details.return_value = details
    task_service.get_task_details_strict.return_value = details
    upload_service.upload_image.return_value = image_url
    sign_service.submit_sign.return_value = sign_success
    executor = SignExecutor(
        config,
        client=client,
        task_service=task_service,
        upload_service=upload_service,
        sign_service=sign_service,
    )
    return executor, client, task_service, upload_service, sign_service


class TestSignExecutor:
    def test_no_pending_tasks_returns_no_task_summary(self) -> None:
        executor, _, _, upload_service, sign_service = create_executor(task_ids=[])

        summary = executor.execute_once(trigger="manual", config_version=4)

        assert summary.status == "no_task"
        assert summary.trigger == "manual"
        assert summary.config_version == 4
        assert summary.discovered_count == 0
        assert summary.task_results == ()
        assert summary.error is None
        upload_service.upload_image.assert_not_called()
        sign_service.submit_sign.assert_not_called()

    def test_successful_task_returns_typed_serializable_summary(self) -> None:
        details = TaskDetails(
            task_id=123,
            position_id=456,
            base_lng=118.237686,
            base_lat=25.077727,
            position_name="测试位置",
        )
        executor, _, _, upload_service, sign_service = create_executor(
            task_ids=["123"], details=details
        )

        summary = executor.execute_once(config_version=9)
        serialized = summary.to_dict()

        assert summary.status == "success"
        assert summary.discovered_count == 1
        assert summary.success_count == 1
        assert summary.failure_count == 0
        assert summary.skipped_count == 0
        assert summary.task_results[0].position_name == "测试位置"
        assert serialized["status"] == "success"
        assert serialized["task_results"][0]["task_id"] == "123"
        assert isinstance(serialized["started_at"], str)
        upload_service.upload_image.assert_called_once_with("test.jpg")
        sign_service.submit_sign.assert_called_once_with(
            task_id=123,
            position_id=456,
            base_lng=118.237686,
            base_lat=25.077727,
            image_url="http://qiniu.example/image.jpg",
        )

    def test_mixed_task_results_return_partial(self) -> None:
        first_details = TaskDetails(1, 11, 118.0, 25.0, "位置一")
        second_details = TaskDetails(2, 22, 119.0, 26.0, "位置二")
        executor, _, task_service, _, sign_service = create_executor(
            task_ids=["1", "2"], details=first_details
        )
        task_service.get_task_details.side_effect = [first_details, second_details]
        sign_service.submit_sign.side_effect = [True, False]

        summary = executor.execute_once()

        assert summary.status == "partial"
        assert summary.discovered_count == 2
        assert summary.success_count == 1
        assert summary.failure_count == 1
        assert [result.status for result in summary.task_results] == ["success", "failed"]
        assert summary.error == "签到提交失败"

    def test_missing_details_is_skipped_and_run_fails(self) -> None:
        executor, _, _, upload_service, _ = create_executor(task_ids=["123"], details=None)

        summary = executor.execute_once()

        assert summary.status == "failed"
        assert summary.skipped_count == 1
        assert summary.failure_count == 0
        assert summary.task_results[0].status == "skipped"
        upload_service.upload_image.assert_not_called()

    def test_capture_fatal_converts_system_exit_to_summary(self) -> None:
        details = TaskDetails(123, 456, 118.0, 25.0, "测试位置")
        executor, _, _, _, sign_service = create_executor(task_ids=["123"], details=details)
        sign_service.submit_sign.side_effect = SystemExit(1)

        summary = executor.execute_once(trigger="manual", capture_fatal=True)

        assert summary.status == "fatal"
        assert summary.discovered_count == 1
        assert summary.failure_count == 1
        assert summary.task_results[0].task_id == "123"
        assert summary.error == "致命请求错误（退出码: 1）"

    def test_default_behavior_propagates_system_exit_for_cli(self) -> None:
        executor, _, task_service, _, _ = create_executor(task_ids=[])
        task_service.get_pending_tasks.side_effect = SystemExit(1)

        with pytest.raises(SystemExit) as exc_info:
            executor.execute_once()

        assert exc_info.value.code == 1

    def test_context_manager_closes_client_once(self) -> None:
        executor, client, _, _, _ = create_executor(task_ids=[])

        with executor:
            executor.execute_once()

        executor.close()
        client.close.assert_called_once_with()

    def test_stop_callback_prevents_starting_next_network_step(self) -> None:
        details = TaskDetails(123, 456, 118.0, 25.0, "测试位置")
        executor, _, task_service, upload_service, sign_service = create_executor(
            task_ids=["123"], details=details
        )
        should_stop = MagicMock(side_effect=[False, True])

        summary = executor.execute_once(should_stop=should_stop)

        assert summary.status == "failed"
        assert summary.error == "执行已停止"
        task_service.get_task_details.assert_called_once_with(123)
        upload_service.upload_image.assert_not_called()
        sign_service.submit_sign.assert_not_called()


class TestCliLoop:
    def test_run_uses_configured_heartbeat_interval(self) -> None:
        config = create_config(heartbeat_interval=37)
        client = MagicMock()
        shutdown = MagicMock()
        shutdown.is_stopped.return_value = False
        shutdown.wait.return_value = True
        task_service = MagicMock()
        task_service.get_pending_tasks.return_value = []

        with (
            patch("fafu_auto_sign.main.load_config", return_value=config),
            patch("fafu_auto_sign.main.setup_logging"),
            patch("fafu_auto_sign.main.FAFUClient") as client_class,
            patch("fafu_auto_sign.main.TaskService", return_value=task_service),
            patch("fafu_auto_sign.main.UploadService", return_value=MagicMock()),
            patch("fafu_auto_sign.main.SignService", return_value=MagicMock()),
            patch("fafu_auto_sign.main.GracefulShutdown", return_value=shutdown),
        ):
            client_class.return_value.__enter__.return_value = client
            client_class.return_value.__exit__.return_value = False

            from fafu_auto_sign.main import run

            run("config.json")

        shutdown.wait.assert_called_once_with(37)


def test_execute_task_once_preserves_detail_upload_sign_order() -> None:
    details = TaskDetails(123, 456, 118.0, 25.0, "测试位置")
    executor, _, task_service, upload_service, sign_service = create_executor(
        task_ids=[], details=details
    )
    calls: list[str] = []
    task_service.get_task_details_strict.side_effect = (
        lambda _task_id: calls.append("details") or details
    )
    upload_service.upload_image.side_effect = lambda _path: calls.append("upload") or "image-url"
    sign_service.submit_sign.side_effect = lambda **_kwargs: calls.append("sign") or True

    summary = executor.execute_task_once("123", config_version=7, capture_fatal=True)

    assert summary.status == "success"
    assert summary.trigger == "manual"
    assert summary.config_version == 7
    assert calls == ["details", "upload", "sign"]
    task_service.get_pending_tasks.assert_not_called()
    task_service.get_task_details_strict.assert_called_once_with(123)


def test_execute_task_once_propagates_strict_details_fetch_error() -> None:
    executor, _, task_service, upload_service, sign_service = create_executor(task_ids=[])
    task_service.get_task_details_strict.side_effect = TaskDetailsFetchError("任务详情请求失败")

    with pytest.raises(TaskDetailsFetchError):
        executor.execute_task_once("123", capture_fatal=True)

    task_service.get_task_details_strict.assert_called_once_with(123)
    upload_service.upload_image.assert_not_called()
    sign_service.submit_sign.assert_not_called()
