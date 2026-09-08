"""Validated persistent image storage."""

from __future__ import annotations

import hashlib
import os
import uuid
from io import BytesIO
from pathlib import Path

from fastapi import UploadFile
from PIL import Image as PillowImage
from PIL import UnidentifiedImageError
from sqlalchemy.orm import Session

from app.models import Image
from app.paths import LATEST_DIR, LIBRARY_DIR

MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_FILES = 10
MAX_IMAGE_PIXELS = 40_000_000
FORMAT_TO_EXTENSION = {
    "JPEG": ".jpg",
    "PNG": ".png",
    "GIF": ".gif",
    "WEBP": ".webp",
}
FORMAT_TO_MIME = {
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "GIF": "image/gif",
    "WEBP": "image/webp",
}
ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


class InvalidImage(ValueError):
    """Raised when uploaded image data fails validation."""


def _validate(content: bytes, original_name: str) -> tuple[str, str]:
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise InvalidImage("仅支持 jpg、jpeg、png、gif、webp 图片")
    if not content:
        raise InvalidImage("图片内容为空")
    if len(content) > MAX_IMAGE_BYTES:
        raise InvalidImage("单张图片不能超过 10 MiB")
    try:
        with PillowImage.open(BytesIO(content)) as image:
            detected = image.format
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise InvalidImage("图片像素尺寸过大")
            image.verify()
    except PillowImage.DecompressionBombError as exc:
        raise InvalidImage("图片像素尺寸过大") from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise InvalidImage("文件不是有效图片") from exc
    if detected not in FORMAT_TO_EXTENSION:
        raise InvalidImage("图片格式不受支持")
    expected = FORMAT_TO_EXTENSION[detected]
    if suffix == ".jpeg":
        suffix = ".jpg"
    if suffix != expected:
        raise InvalidImage("文件扩展名与实际图片格式不一致")
    return expected, FORMAT_TO_MIME[detected]


def store_bytes(
    session: Session,
    content: bytes,
    original_name: str,
    purpose: str,
    *,
    commit: bool = True,
) -> Image:
    """Validate and atomically persist bytes plus metadata."""
    if purpose not in {"library", "latest"}:
        raise InvalidImage("图片用途必须为 library 或 latest")
    extension, mime = _validate(content, original_name)
    image_id = str(uuid.uuid4())
    storage_name = f"{image_id}{extension}"
    root = LIBRARY_DIR if purpose == "library" else LATEST_DIR
    root.mkdir(parents=True, exist_ok=True)
    final_path = root / storage_name
    temp_path = root / f".{storage_name}.tmp"
    try:
        temp_path.write_bytes(content)
        os.replace(temp_path, final_path)
        row = Image(
            id=image_id,
            purpose=purpose,
            original_name=Path(original_name).name,
            storage_name=storage_name,
            mime_type=mime,
            size=len(content),
            sha256=hashlib.sha256(content).hexdigest(),
        )
        session.add(row)
        session.flush()
        if commit:
            session.commit()
            session.refresh(row)
    except Exception:
        session.rollback()
        temp_path.unlink(missing_ok=True)
        final_path.unlink(missing_ok=True)
        raise
    return row


async def store_upload(
    session: Session,
    upload: UploadFile,
    purpose: str,
    *,
    commit: bool = True,
) -> Image:
    """Read a bounded upload and persist it."""
    content = await upload.read(MAX_IMAGE_BYTES + 1)
    await upload.close()
    return store_bytes(session, content, upload.filename or "upload", purpose, commit=commit)
