"""Simple file-based JSON cache."""

import json
import time
from pathlib import Path
from typing import Any

CACHE_DIR = Path.home() / ".cache" / "ppm"
DEFAULT_TTL = 3600  # 1 hour


def _cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.json"


def get(key: str, ttl: int = DEFAULT_TTL) -> Any | None:
    path = _cache_path(key)
    if not path.exists():
        return None
    if time.time() - path.stat().st_mtime > ttl:
        return None
    return json.loads(path.read_text())


def set(key: str, data: Any) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    _cache_path(key).write_text(json.dumps(data))


def invalidate(key: str) -> None:
    path = _cache_path(key)
    if path.exists():
        path.unlink()
