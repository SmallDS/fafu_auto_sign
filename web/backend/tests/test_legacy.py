from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.legacy import IMPORT_META_KEY, import_legacy_config
from app.repository import get_meta


def test_missing_legacy_file_does_not_consume_future_import(
    db_session: Session,
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr("app.legacy._candidate_paths", lambda: [tmp_path / "missing.json"])

    assert import_legacy_config(db_session) is None
    assert get_meta(db_session, IMPORT_META_KEY) is None
