"""Safe, per-user avatar storage."""

from __future__ import annotations

import os
import uuid
from io import BytesIO
from pathlib import Path
from urllib.parse import urlparse

import requests
from PIL import Image as PillowImage
from PIL import UnidentifiedImageError

from app.paths import user_avatar_dir

MAX_AVATAR_BYTES = 2 * 1024 * 1024
FORMATS = {"JPEG": ".jpg", "PNG": ".png", "WEBP": ".webp"}
MIMES = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}


class InvalidAvatar(ValueError):
    pass


def _validate(content: bytes) -> tuple[str, str]:
    if not content or len(content) > MAX_AVATAR_BYTES:
        raise InvalidAvatar("头像为空或超过 2 MiB")
    try:
        with PillowImage.open(BytesIO(content)) as image:
            detected = image.format
            if image.width * image.height > 16_000_000:
                raise InvalidAvatar("头像像素尺寸过大")
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise InvalidAvatar("头像不是有效图片") from exc
    if detected not in FORMATS:
        raise InvalidAvatar("头像仅支持 JPEG、PNG 或 WebP")
    return FORMATS[detected], MIMES[detected]


def store_avatar(user_id: str, content: bytes) -> tuple[str, str]:
    extension, mime = _validate(content)
    root = user_avatar_dir(user_id)
    root.mkdir(parents=True, exist_ok=True)
    storage_name = f"{uuid.uuid4()}{extension}"
    final_path = root / storage_name
    temp_path = root / f".{storage_name}.tmp"
    temp_path.write_bytes(content)
    os.replace(temp_path, final_path)
    return storage_name, mime


def download_wechat_avatar(user_id: str, url: str) -> str | None:
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (
        host == "qlogo.cn" or host.endswith(".qlogo.cn") or host.endswith(".qpic.cn")
    ):
        return None
    try:
        response = requests.get(
            url,
            timeout=(5, 10),
            allow_redirects=False,
            stream=True,
            headers={"User-Agent": "FAFU-Auto-Sign/1.0"},
        )
        response.raise_for_status()
        length = response.headers.get("content-length")
        if length and int(length) > MAX_AVATAR_BYTES:
            return None
        content = response.raw.read(MAX_AVATAR_BYTES + 1)
        storage_name, _ = store_avatar(user_id, content)
        return storage_name
    except (requests.RequestException, ValueError, InvalidAvatar):
        return None


def avatar_path(user_id: str, storage_name: str) -> Path:
    root = user_avatar_dir(user_id).resolve()
    path = (root / storage_name).resolve()
    if root not in path.parents:
        raise InvalidAvatar("头像路径越界")
    return path