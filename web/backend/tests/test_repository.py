from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Image
from fafu_auto_sign.executor import RunSummary, TaskRunResult
from app.repository import (
    get_or_create_settings,
    save_run_summary,
    settings_to_read,
    update_settings,
)
from app.schemas import SettingsUpdate


def test_secrets_are_masked_preserved_and_explicitly_cleared(db_session: Session) -> None:
    settings = get_or_create_settings(db_session)
    settings.user_token = "2_very_secret_token"
    db_session.commit()

    public = settings_to_read(db_session, settings)
    assert public.has_user_token is True
    assert public.user_token_masked != settings.user_token

    updated = update_settings(
        db_session,
        SettingsUpdate(user_token="", jitter=0.0001),
    )
    assert updated.user_token == "2_very_secret_token"

    cleared = update_settings(
        db_session,
        SettingsUpdate(clear_user_token=True),
    )
    assert cleared.user_token is None


def test_fixed_image_selection_must_reference_library_image(
    db_session: Session,
    tmp_path: Path,
    monkeypatch,
) -> None:
    import app.repository as repository

    monkeypatch.setattr(repository, "LIBRARY_DIR", tmp_path / "library")
    monkeypatch.setattr(repository, "LATEST_DIR", tmp_path / "latest")
    (tmp_path / "latest").mkdir()
    image = Image(
        id="latest-id",
        purpose="latest",
        original_name="latest.png",
        storage_name="latest-id.png",
        mime_type="image/png",
        size=1,
        sha256="0" * 64,
    )
    db_session.add(image)
    db_session.commit()

    try:
        update_settings(
            db_session,
            SettingsUpdate(image_mode="single", selected_image_id=image.id),
        )
    except ValueError as exc:
        assert "图库" in str(exc)
    else:
        raise AssertionError("latest 图片不应被允许作为固定图库图片")


def test_run_history_redacts_sensitive_exception_text(db_session: Session) -> None:
    now = datetime.now(timezone.utc)
    secret = (
        "https://example.test/path?signImg=http://secret "
        "Authorization=Bearer-secret user_token=2_hidden "
    )
    summary = RunSummary(
        trigger="manual",
        config_version=1,
        status="failed",
        started_at=now,
        finished_at=now,
        task_results=(
            TaskRunResult(
                task_id="7",
                status="failed",
                started_at=now,
                finished_at=now,
                image_url="https://image.test/file?token=hidden",
                error=secret,
            ),
        ),
        error=secret,
        discovered_task_count=1,
    )

    row = save_run_summary(db_session, summary)
    persisted = " ".join(
        [row.summary, row.error or "", json.dumps(json.loads(row.task_details_json))]
    )

    assert "Bearer-secret" not in persisted
    assert "2_hidden" not in persisted
    assert "token=hidden" not in persisted
    assert "signImg=http://secret" not in persisted
