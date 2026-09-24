from __future__ import annotations

import uuid
from datetime import timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy.orm import Session, sessionmaker

import app.worker as worker_module
from app.models import SignJob, User, utcnow
from app.repository import get_or_create_settings, get_or_create_system_settings
from fafu_auto_sign.executor import RunSummary


@pytest.mark.parametrize(
    ("http_status", "force_calls", "worker_enabled"),
    [(401, 1, True), (408, 0, False)],
)
def test_worker_refreshes_only_401_and_does_not_replay_sign(
    db_session: Session, monkeypatch, http_status: int,
    force_calls: int, worker_enabled: bool,
) -> None:
    account = User(
        id=str(uuid.uuid4()), openid="worker-" + str(uuid.uuid4()),
        nickname="测试", role="user", status="active",
    )
    db_session.add(account)
    system = get_or_create_system_settings(db_session)
    system.setup_state = "initialized"
    settings = get_or_create_settings(db_session, account.id)
    settings.user_token = "2_old"
    settings.fafu_auth_mode = "auto"
    settings.worker_enabled = True
    job = SignJob(
        id=str(uuid.uuid4()), user_id=account.id,
        kind="scheduled", priority=20, status="running",
    )
    db_session.add(job)
    db_session.commit()

    started = utcnow()
    summary = RunSummary(
        trigger="scheduled", config_version=settings.config_version,
        status="fatal", started_at=started, finished_at=started + timedelta(seconds=1),
        error="FAFU 鉴权或时间校验失败", fatal_http_status=http_status,
    )
    calls: list[bool] = []

    def ensure_token(session, user_id, *, force_refresh=False):
        assert user_id == account.id
        calls.append(force_refresh)
        return "2_new" if force_refresh else "2_old"

    class FakeExecutor:
        def __init__(self, config):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def execute_once(self, **kwargs):
            return summary

    monkeypatch.setattr(worker_module, "SessionLocal", sessionmaker(
        bind=db_session.get_bind(), expire_on_commit=False, autoflush=False,
    ))
    monkeypatch.setattr(worker_module, "build_app_config", lambda *args: SimpleNamespace())
    monkeypatch.setattr(worker_module, "SignExecutor", FakeExecutor)
    monkeypatch.setattr(worker_module.fafu_auth, "ensure_token", ensure_token)
    monkeypatch.setattr(worker_module, "NotificationService", lambda config: SimpleNamespace(
        notify_summary=lambda value: None,
    ))

    worker_module.WorkerManager()._execute_job(job.id)
    db_session.expire_all()
    assert calls == [False] + ([True] if force_calls else [])
    assert get_or_create_settings(db_session, account.id).worker_enabled is worker_enabled
    assert db_session.get(SignJob, job.id).status == "completed"
