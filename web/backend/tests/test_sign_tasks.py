from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

import app.manual_sign as manual_module
from app.database import get_db
from app.main import app, manual_sign
from app.manual_sign import (
    ExecutionBusy,
    ManualSignService,
    TaskNoLongerActive,
    UpstreamUnavailable,
)
from app.models import Image, RunHistory
from app.repository import get_or_create_settings
from app.worker import WorkerManager
from fafu_auto_sign.executor import RunSummary, TaskRunResult
from fafu_auto_sign.services.task_service import (
    SignTask,
    SignTaskPage,
    TaskDetails,
    TaskDetailsFetchError,
    TaskService,
)


def configure_signing(db_session: Session, tmp_path, monkeypatch) -> None:
    import app.repository as repository

    library = tmp_path / "library"
    library.mkdir()
    (library / "image.png").write_bytes(b"image")
    monkeypatch.setattr(repository, "LIBRARY_DIR", library)
    image = Image(
        id="manual-image",
        purpose="library",
        original_name="image.png",
        storage_name="image.png",
        mime_type="image/png",
        size=5,
        sha256="0" * 64,
    )
    db_session.add(image)
    settings = get_or_create_settings(db_session)
    settings.user_token = "2_manual_test"
    settings.image_mode = "single"
    settings.current_image_id = image.id
    settings.worker_enabled = False
    db_session.commit()


def test_manual_submit_rechecks_page_persists_history_and_stays_paused(
    db_session: Session, tmp_path, monkeypatch
) -> None:
    configure_signing(db_session, tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    task_page = SignTaskPage(
        items=(
            SignTask(
                id="7",
                name="课堂签到",
                begin_time=int((now - timedelta(minutes=1)).timestamp() * 1000),
                end_time=int((now + timedelta(minutes=1)).timestamp() * 1000),
            ),
        ),
        page=2,
        page_size=10,
        total=None,
        has_more=False,
    )
    task_result = TaskRunResult("7", "success", now, now, position_name="宿舍")
    summary = RunSummary(
        trigger="manual",
        config_version=1,
        status="success",
        started_at=now,
        finished_at=now,
        task_results=(task_result,),
        discovered_task_count=1,
    )
    fake = SimpleNamespace(
        task_service=SimpleNamespace(get_pending_task_page=lambda page, size: task_page),
        execute_task_once=lambda *args, **kwargs: summary,
        __enter__=lambda self: self,
        __exit__=lambda *args: None,
    )

    class FakeExecutor:
        def __init__(self, _config) -> None:
            self.task_service = fake.task_service

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def execute_task_once(self, *args, **kwargs):
            assert args == ("7",)
            assert kwargs["capture_fatal"] is True
            return summary

    monkeypatch.setattr(manual_module, "SignExecutor", FakeExecutor)
    worker = WorkerManager()
    service = ManualSignService(worker)

    row = service.submit(db_session, task_id=7, source_page=2, page_size=10)

    persisted = db_session.scalar(select(RunHistory).where(RunHistory.id == row.id))
    assert persisted is not None
    assert persisted.trigger == "manual"
    assert persisted.status == "success"
    assert persisted.success_count == 1
    assert worker.snapshot()["state"] == "paused"


def test_external_execution_slot_is_released_after_upstream_error(
    db_session: Session, tmp_path, monkeypatch
) -> None:
    configure_signing(db_session, tmp_path, monkeypatch)

    class BrokenExecutor:
        def __init__(self, _config) -> None:
            self.task_service = SimpleNamespace(
                get_pending_task_page=lambda _page, _size: (_ for _ in ()).throw(RuntimeError())
            )

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    monkeypatch.setattr(manual_module, "SignExecutor", BrokenExecutor)
    worker = WorkerManager()
    service = ManualSignService(worker)

    with pytest.raises(UpstreamUnavailable):
        service.submit(db_session, task_id=7, source_page=1, page_size=20)

    assert worker.try_begin_external_execution() is True
    assert worker.try_begin_external_execution() is False
    worker.finish_external_execution(configured=True, worker_enabled=False)
    assert worker.snapshot()["state"] == "paused"


def test_sign_task_list_api_returns_nullable_total(db_session: Session, monkeypatch) -> None:
    task_page = SignTaskPage(
        items=(SignTask("9", "任意签到", 1, 2),),
        page=1,
        page_size=20,
        total=None,
        has_more=False,
    )
    monkeypatch.setattr(manual_sign, "list_tasks", lambda _session, _page, _page_size: task_page)

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        response = client.get("/api/sign-tasks?page=1&page_size=20")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json() == {
        "items": [{"id": "9", "name": "任意签到", "begin_time": 1, "end_time": 2}],
        "total": None,
        "page": 1,
        "page_size": 20,
        "has_more": False,
    }


def test_sign_task_detail_submit_and_busy_api_mapping(db_session: Session, monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    run = RunHistory(
        id=33,
        trigger="manual",
        config_version=4,
        started_at=now,
        finished_at=now,
        status="success",
        discovered_count=1,
        success_count=1,
        failure_count=0,
        summary="签到成功",
        task_details_json="[]",
    )
    monkeypatch.setattr(
        manual_sign,
        "get_details",
        lambda _session, task_id: TaskDetails(task_id, 456, 118.1, 25.1, "宿舍楼"),
    )
    submit = lambda _session, task_id, source_page, page_size: run
    monkeypatch.setattr(manual_sign, "submit", submit)

    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        details = client.get("/api/sign-tasks/123")
        submitted = client.post(
            "/api/sign-tasks/123/submit",
            json={"source_page": 2, "page_size": 10},
        )
        monkeypatch.setattr(
            manual_sign,
            "submit",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(ExecutionBusy()),
        )
        busy = client.post(
            "/api/sign-tasks/123/submit",
            json={"source_page": 2, "page_size": 10},
        )
    finally:
        app.dependency_overrides.clear()

    assert details.status_code == 200
    assert details.json()["position_name"] == "宿舍楼"
    assert submitted.status_code == 200
    assert submitted.json()["id"] == 33
    assert submitted.json()["trigger"] == "manual"
    assert busy.status_code == 409
    assert busy.json()["detail"]["code"] == "WORKER_BUSY"


def test_all_web_fafu_operations_share_one_execution_slot(
    db_session: Session, tmp_path, monkeypatch
) -> None:
    configure_signing(db_session, tmp_path, monkeypatch)
    worker = WorkerManager()
    service = ManualSignService(worker)
    assert worker.try_begin_external_execution() is True
    assert worker.request_run_now() is False

    with pytest.raises(ExecutionBusy):
        service.list_tasks(db_session, 1, 20)
    with pytest.raises(ExecutionBusy):
        service.get_details(db_session, 7)
    with pytest.raises(ExecutionBusy):
        service.submit(db_session, 7, 1, 20)

    worker.finish_external_execution(configured=True, worker_enabled=False)


@pytest.mark.parametrize("operation", ["list", "details"])
def test_read_only_system_exit_disables_worker(
    operation: str, db_session: Session, monkeypatch
) -> None:
    settings = get_or_create_settings(db_session)
    settings.user_token = "2_read_fatal"
    settings.worker_enabled = True
    db_session.commit()

    class FatalClient:
        def __init__(self, _config) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def post(self, *_args, **_kwargs):
            raise SystemExit(401)

        def get(self, *_args, **_kwargs):
            raise SystemExit(408)

    monkeypatch.setattr(manual_module, "FAFUClient", FatalClient)
    service = ManualSignService(WorkerManager())

    with pytest.raises(UpstreamUnavailable):
        if operation == "list":
            service.list_tasks(db_session, 1, 20)
        else:
            service.get_details(db_session, 7)

    db_session.refresh(settings)
    assert settings.worker_enabled is False


def test_details_network_failure_is_safe_upstream_error(db_session: Session, monkeypatch) -> None:
    settings = get_or_create_settings(db_session)
    settings.user_token = "2_detail_network"
    db_session.commit()

    class BrokenClient:
        def __init__(self, _config) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def get(self, *_args, **_kwargs):
            raise RuntimeError(
                "Authorization=secret user_token=2_secret signImg=http://host/img?a=1"
            )

    monkeypatch.setattr(manual_module, "FAFUClient", BrokenClient)
    with pytest.raises(UpstreamUnavailable) as caught:
        ManualSignService(WorkerManager()).get_details(db_session, 7)

    assert "secret" not in str(caught.value)


def test_inactive_task_writes_one_failed_history_with_run_id(
    db_session: Session, tmp_path, monkeypatch
) -> None:
    configure_signing(db_session, tmp_path, monkeypatch)
    page = SignTaskPage(
        items=(SignTask("7", "已过期", 1, 2),),
        page=1,
        page_size=20,
        total=1,
        has_more=False,
    )

    class InactiveExecutor:
        def __init__(self, _config) -> None:
            self.task_service = SimpleNamespace(get_pending_task_page=lambda *_args: page)

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    monkeypatch.setattr(manual_module, "SignExecutor", InactiveExecutor)
    service = ManualSignService(WorkerManager())

    with pytest.raises(TaskNoLongerActive) as caught:
        service.submit(db_session, 7, 1, 20)

    rows = db_session.scalars(select(RunHistory)).all()
    assert len(rows) == 1
    assert rows[0].id == caught.value.run_id
    assert rows[0].status == "failed"
    assert '"task_id": "7"' in rows[0].task_details_json


def test_submit_system_exit_writes_fatal_history_and_disables_worker(
    db_session: Session, tmp_path, monkeypatch
) -> None:
    configure_signing(db_session, tmp_path, monkeypatch)
    settings = get_or_create_settings(db_session)
    settings.worker_enabled = True
    settings.wechat_test_enabled = True
    settings.wechat_test_app_id = "wx-app-id"
    settings.wechat_test_app_secret = "app-secret"
    settings.wechat_test_template_id = "template-id"
    settings.wechat_test_openid = "openid"
    db_session.commit()

    notified_configs = []

    class CapturingNotificationService:
        def __init__(self, config) -> None:
            notified_configs.append(config)

        def notify_summary(self, _summary) -> bool:
            return True

    class FatalExecutor:
        def __init__(self, _config) -> None:
            self.task_service = SimpleNamespace(
                get_pending_task_page=lambda *_args: (_ for _ in ()).throw(
                    SystemExit("Authorization=secret&user_token=2_secret")
                )
            )

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

    monkeypatch.setattr(manual_module, "SignExecutor", FatalExecutor)
    monkeypatch.setattr(manual_module, "NotificationService", CapturingNotificationService)
    service = ManualSignService(WorkerManager())

    with pytest.raises(UpstreamUnavailable) as caught:
        service.submit(db_session, 7, 1, 20)

    rows = db_session.scalars(select(RunHistory)).all()
    assert len(rows) == 1
    assert rows[0].id == caught.value.run_id
    assert rows[0].status == "fatal"
    assert "secret" not in (rows[0].error or "")
    db_session.refresh(settings)
    assert settings.worker_enabled is False
    assert len(notified_configs) == 1
    assert notified_configs[0].wechat_test_enabled is True


def test_release_slot_survives_database_recovery_failure(db_session: Session, monkeypatch) -> None:
    settings = get_or_create_settings(db_session)
    settings.user_token = "2_release_test"
    db_session.commit()
    real_get_settings = manual_module.get_or_create_settings
    calls = 0

    def flaky_get_settings(session):
        nonlocal calls
        calls += 1
        if calls == 1:
            return real_get_settings(session)
        raise RuntimeError("database unavailable")

    class EmptyClient:
        def __init__(self, _config) -> None:
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def post(self, *_args, **_kwargs):
            return SimpleNamespace(json=lambda: {"records": [], "total": 0})

    monkeypatch.setattr(manual_module, "get_or_create_settings", flaky_get_settings)
    monkeypatch.setattr(manual_module, "FAFUClient", EmptyClient)
    worker = WorkerManager()
    service = ManualSignService(worker)

    assert service.list_tasks(db_session, 1, 20).items == ()
    assert worker.try_begin_external_execution() is True
    worker.finish_external_execution(configured=False, worker_enabled=False)


def test_api_maps_detail_upstream_and_inactive_run_id(db_session: Session, monkeypatch) -> None:
    def override_db():
        yield db_session

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        monkeypatch.setattr(
            manual_sign,
            "get_details",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(UpstreamUnavailable()),
        )
        upstream = client.get("/api/sign-tasks/7")
        monkeypatch.setattr(
            manual_sign,
            "submit",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(TaskNoLongerActive(88)),
        )
        inactive = client.post(
            "/api/sign-tasks/7/submit",
            json={"source_page": 1, "page_size": 20},
        )
    finally:
        app.dependency_overrides.clear()

    assert upstream.status_code == 502
    assert upstream.json()["detail"]["message"] == "无法读取 FAFU 任务详情"
    assert inactive.status_code == 409
    assert inactive.json()["detail"]["fields"]["run_id"] == "88"


def test_submit_detail_network_failure_uses_real_executor_and_returns_safe_502(
    db_session: Session, tmp_path, monkeypatch
) -> None:
    configure_signing(db_session, tmp_path, monkeypatch)
    now = datetime.now(timezone.utc)
    active_page = SignTaskPage(
        items=(
            SignTask(
                "7",
                "进行中",
                int((now - timedelta(minutes=1)).timestamp() * 1000),
                int((now + timedelta(minutes=1)).timestamp() * 1000),
            ),
        ),
        page=1,
        page_size=20,
        total=1,
        has_more=False,
    )
    monkeypatch.setattr(
        TaskService,
        "get_pending_task_page",
        lambda _self, _page, _page_size: active_page,
    )
    monkeypatch.setattr(
        TaskService,
        "get_task_details_strict",
        lambda _self, _task_id: (_ for _ in ()).throw(
            TaskDetailsFetchError(
                "Authorization=secret user_token=2_secret signImg=http://image?token=secret"
            )
        ),
    )
    service = ManualSignService(WorkerManager())

    with pytest.raises(UpstreamUnavailable) as caught:
        service.submit(db_session, 7, 1, 20)

    rows = db_session.scalars(select(RunHistory)).all()
    assert len(rows) == 1
    assert rows[0].id == caught.value.run_id
    assert rows[0].status == "failed"
    persisted = f"{rows[0].summary} {rows[0].error} {rows[0].task_details_json}"
    assert "secret" not in persisted
    assert "FAFU 请求失败" in persisted
