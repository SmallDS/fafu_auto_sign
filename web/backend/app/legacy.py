"""One-time import of legacy JSON configuration and local images."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.image_store import InvalidImage, store_bytes
from app.paths import DATA_DIR, REPOSITORY_DIR
from app.repository import get_meta, get_or_create_settings, set_meta

logger = logging.getLogger(__name__)
IMPORT_META_KEY = "legacy_config_imported"


def _candidate_paths() -> list[Path]:
    candidates: list[Path] = []
    env_path = os.getenv("FAFU_LEGACY_CONFIG_PATH")
    if env_path:
        candidates.append(Path(env_path))
    candidates.extend([DATA_DIR / "import" / "config.json", REPOSITORY_DIR / "config.json"])
    unique: list[Path] = []
    for candidate in candidates:
        resolved = candidate.expanduser().resolve()
        if resolved not in unique:
            unique.append(resolved)
    return unique


def _copy_image(session: Session, path: Path, purpose: str) -> str | None:
    try:
        if not path.is_file():
            return None
        image = store_bytes(session, path.read_bytes(), path.name, purpose)
        return image.id
    except (OSError, InvalidImage) as exc:
        logger.warning("旧图片无法导入 %s: %s", path, exc)
        return None


def import_legacy_config(session: Session) -> Path | None:
    """Import the first existing legacy config exactly once."""
    if get_meta(session, IMPORT_META_KEY) is not None:
        return None
    source = next((path for path in _candidate_paths() if path.is_file()), None)
    if source is None:
        return None
    try:
        data: dict[str, Any] = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("无法读取旧配置 %s: %s", source, exc)
        return None

    settings = get_or_create_settings(session)
    token = data.get("user_token")
    if isinstance(token, str) and token.startswith("2_"):
        settings.user_token = token
    jitter = data.get("jitter")
    if isinstance(jitter, (int, float)) and 0 <= float(jitter) <= 0.001:
        settings.jitter = float(jitter)
    interval = data.get("heartbeat_interval")
    if isinstance(interval, int) and 10 <= interval <= 86400:
        settings.heartbeat_interval = interval
    level = str(data.get("log_level", "INFO")).upper()
    if level in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        settings.log_level = level
    keywords = data.get("task_keywords")
    if isinstance(keywords, list) and all(
        isinstance(item, str) and item.strip() for item in keywords
    ):
        settings.task_keywords_json = json.dumps(keywords, ensure_ascii=False)
    settings.wechat_test_enabled = bool(data.get("wechat_test_enabled", False))
    for field in ("wechat_test_app_id", "wechat_test_app_secret", "wechat_test_template_id", "wechat_test_openid"):
        value = data.get(field)
        if isinstance(value, str) and value:
            setattr(settings, field, value)

    base = source.parent
    imported_single: str | None = None
    image_path_value = data.get("image_path")
    if isinstance(image_path_value, str):
        candidate = Path(image_path_value)
        imported_single = _copy_image(
            session, candidate if candidate.is_absolute() else base / candidate, "library"
        )
    for field, purpose in (("image_dir", "library"), ("latest_image_dir", "latest")):
        raw_dir = data.get(field)
        if not isinstance(raw_dir, str):
            continue
        directory = Path(raw_dir)
        directory = directory if directory.is_absolute() else base / directory
        if directory.is_dir():
            for child in sorted(directory.iterdir()):
                if child.is_file():
                    _copy_image(session, child, purpose)
        else:
            logger.warning("旧图片目录不可访问: %s", directory)

    if data.get("latest_image_dir"):
        settings.image_mode = "latest"
    elif data.get("image_dir"):
        settings.image_mode = "library"
    else:
        settings.image_mode = "single"
        settings.current_image_id = imported_single
    settings.config_version += 1
    session.commit()
    set_meta(session, IMPORT_META_KEY, str(source))
    logger.info("已从 %s 导入旧配置", source)
    return source
