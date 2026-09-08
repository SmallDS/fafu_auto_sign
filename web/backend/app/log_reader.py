"""Cursor-based structured log reader."""

from __future__ import annotations

import json

from app.paths import LOG_FILE
from app.schemas import LogEntry, LogPage


def read_logs(cursor: int, limit: int, level: str | None) -> LogPage:
    """Read at most ``limit`` entries while advancing a byte cursor."""
    if not LOG_FILE.exists():
        return LogPage(entries=[], next_cursor=0, reset=cursor > 0)
    size = LOG_FILE.stat().st_size
    reset = cursor > size
    position = 0 if reset else max(0, cursor)
    items: list[LogEntry] = []
    with LOG_FILE.open("rb") as handle:
        handle.seek(position)
        while len(items) < limit:
            line = handle.readline()
            if not line:
                break
            position = handle.tell()
            try:
                raw = json.loads(line.decode("utf-8"))
                entry = LogEntry(
                    timestamp=str(raw.get("timestamp", "")),
                    level=str(raw.get("level", "INFO")),
                    logger=str(raw.get("name", "app")),
                    message=str(raw.get("message", "")),
                )
            except (UnicodeDecodeError, json.JSONDecodeError):
                entry = LogEntry(
                    timestamp="",
                    level="INFO",
                    logger="app",
                    message=line.decode("utf-8", errors="replace").rstrip(),
                )
            if level is None or entry.level.upper() == level.upper():
                items.append(entry)
    return LogPage(entries=items, next_cursor=position, reset=reset)
