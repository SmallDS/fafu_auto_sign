from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from app.models import Image
from app.repository import get_or_create_settings, settings_to_read, update_settings
from app.schemas import SettingsUpdate


def test_secrets_are_masked_preserved_and_explicitly_cleared(db_session: Session) -> None:
    settings = get_or_create_settings(db_session)
    settings.user_token = "2_very_secret_token"
    settings.serverchan_key = "SC3_very_secret_key"
    db_session.commit()

    public = settings_to_read(db_session, settings)
    assert public.has_user_token is True
    assert public.user_token_masked != settings.user_token
    assert public.serverchan_key_masked != settings.serverchan_key

    updated = update_settings(
        db_session,
        SettingsUpdate(user_token="", serverchan_key=None, jitter=0.0001),
    )
    assert updated.user_token == "2_very_secret_token"
    assert updated.serverchan_key == "SC3_very_secret_key"

    cleared = update_settings(
        db_session,
        SettingsUpdate(clear_user_token=True, clear_serverchan_key=True),
    )
    assert cleared.user_token is None
    assert cleared.serverchan_key is None


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
