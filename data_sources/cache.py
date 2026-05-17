"""On-disk cache for API responses.

EDGAR companyfacts payloads can be 5-10 MB and they only change quarterly,
so caching them aggressively makes the app feel instant and is gentle on
the SEC's servers.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

CACHE_DIR = Path(os.path.expanduser("~/.cache/brevity"))


def _slugify(s: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in s)[:80]


def _key_to_path(key: str) -> Path:
    safe = _slugify(key)
    if len(safe) < 80 and safe == key.replace("/", "_"):
        return CACHE_DIR / f"{safe}.json"
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]
    return CACHE_DIR / f"{safe[:40]}__{digest}.json"


def get(key: str, ttl_seconds: int) -> Any | None:
    path = _key_to_path(key)
    if not path.exists():
        return None
    try:
        age = time.time() - path.stat().st_mtime
        if age > ttl_seconds:
            return None
        with path.open("r") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None


def put(key: str, value: Any) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        path = _key_to_path(key)
        with tempfile.NamedTemporaryFile(
            "w", dir=CACHE_DIR, delete=False, suffix=".tmp"
        ) as tmp:
            json.dump(value, tmp)
            tmp_path = Path(tmp.name)
        tmp_path.replace(path)
    except OSError:
        pass


def clear() -> int:
    if not CACHE_DIR.exists():
        return 0
    count = 0
    for f in CACHE_DIR.glob("*.json"):
        try:
            f.unlink()
            count += 1
        except OSError:
            pass
    return count
