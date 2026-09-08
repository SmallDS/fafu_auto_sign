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
LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "fafu_sign.log"
FRONTEND_DIST = WEB_DIR / "frontend" / "dist"


def ensure_data_directories() -> None:
    """Create all persistent directories required by the service."""
    for path in (DATA_DIR, LIBRARY_DIR, LATEST_DIR, LOG_DIR):
        path.mkdir(parents=True, exist_ok=True)
