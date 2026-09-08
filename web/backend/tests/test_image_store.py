from __future__ import annotations

from io import BytesIO
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image as PillowImage
from sqlalchemy.orm import Session

from app.image_store import InvalidImage, store_bytes


def png_bytes() -> bytes:
    output = BytesIO()
    PillowImage.new("RGB", (2, 2), color="white").save(output, format="PNG")
    return output.getvalue()


def test_image_content_is_verified_and_saved_with_uuid_name(
    db_session: Session,
    tmp_path: Path,
    monkeypatch,
) -> None:
    import app.image_store as image_store

    library = tmp_path / "library"
    monkeypatch.setattr(image_store, "LIBRARY_DIR", library)
    monkeypatch.setattr(image_store, "LATEST_DIR", tmp_path / "latest")

    row = store_bytes(db_session, png_bytes(), "../../camera.png", "library")

    assert row.original_name == "camera.png"
    assert row.storage_name == f"{row.id}.png"
    assert (library / row.storage_name).is_file()


def test_forged_extension_is_rejected(
    db_session: Session,
    tmp_path: Path,
    monkeypatch,
) -> None:
    import app.image_store as image_store

    monkeypatch.setattr(image_store, "LIBRARY_DIR", tmp_path / "library")
    monkeypatch.setattr(image_store, "LATEST_DIR", tmp_path / "latest")

    with pytest.raises(InvalidImage, match="扩展名"):
        store_bytes(db_session, png_bytes(), "camera.jpg", "library")


def test_excessive_pixel_dimensions_are_rejected() -> None:
    fake_image = MagicMock()
    fake_image.__enter__.return_value = fake_image
    fake_image.format = "PNG"
    fake_image.width = 10_000
    fake_image.height = 10_000

    with (
        patch("app.image_store.PillowImage.open", return_value=fake_image),
        pytest.raises(InvalidImage, match="像素尺寸"),
    ):
        from app.image_store import _validate

        _validate(b"small compressed payload", "large.png")
