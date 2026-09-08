from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.config_adapter import FIXED_BASE_URL, build_app_config
from app.models import Image
from app.repository import get_or_create_settings


def test_web_snapshot_keeps_fixed_plain_http_base_url(
    db_session: Session,
    tmp_path: Path,
    monkeypatch,
) -> None:
    import app.repository as repository

    library = tmp_path / "library"
    library.mkdir()
    storage_name = "fixed.png"
    (library / storage_name).write_bytes(b"image")
    monkeypatch.setattr(repository, "LIBRARY_DIR", library)

    image = Image(
        id="fixed-image-id",
        purpose="library",
        original_name="fixed.png",
        storage_name=storage_name,
        mime_type="image/png",
        size=5,
        sha256="0" * 64,
    )
    db_session.add(image)
    settings = get_or_create_settings(db_session)
    settings.user_token = "2_test_token"
    settings.image_mode = "single"
    settings.current_image_id = image.id
    db_session.commit()

    config = build_app_config(db_session, settings)

    assert config.base_url == FIXED_BASE_URL == "http://stuhtapi.fafu.edu.cn"
