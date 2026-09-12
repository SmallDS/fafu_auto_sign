"""Filesystem paths used by the Web service."""

from __future__ import annotations

import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = BACKEND_DIR.parent
REPOSITORY_DIR = WEB_DIR.parent
DATA_DIR = Path(os.getenv("FAFU_DATA_DIR", "/data")).resolve()
DATABASE_PATH = Path(os.getenv("FAFU_DATABASE_PATH", str(DATA_DIR / "app.db"))).resolve()
IMAGE_ROOT = DATA_DIR / "images"
LIBRARY_DIR = IMAGE_ROOT / "library"
LATEST_DIR = IMAGE_ROOT / "latest"
USERS_DIR = DATA_DIR / "users"
LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "fafu_sign.log"
FRONTEND_DIST = WEB_DIR / "frontend" / "dist"


def user_root(user_id: str) -> Path:
    if not user_id or "/" in user_id or "\\" in user_id or ".." in user_id:
        raise ValueError("用户目录标识无效")
    return USERS_DIR / user_id


def user_image_dir(user_id: str, purpose: str) -> Path:
    if purpose not in {"library", "latest"}:
        raise ValueError("图片用途无效")
    return user_root(user_id) / "images" / purpose


def user_avatar_dir(user_id: str) -> Path:
    return user_root(user_id) / "avatar"


def ensure_data_directories() -> None:
    """Create persistent system-level directories."""
    for path in (DATA_DIR, USERS_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)