import hashlib
import json
import time
from pathlib import Path
from typing import Callable, List, TypeVar

from app.core.config import settings

T = TypeVar("T")


class MarkerCache:
    """Small disk cache for marker indexes keyed by uploaded file content."""

    MAX_ENTRIES = 100
    MAX_AGE_SECONDS = 24 * 60 * 60

    @classmethod
    def key(cls, file_bytes: bytes, kind: str) -> str:
        digest = hashlib.sha256(file_bytes).hexdigest()
        return f"{kind}_{digest}.json"

    @classmethod
    def get_or_create(cls, file_bytes: bytes, kind: str, factory: Callable[[], T], dump: Callable[[T], list], load: Callable[[list], T]) -> T:
        cache_dir = settings.STORAGE_DIR / "marker_cache"
        cache_dir.mkdir(parents=True, exist_ok=True)
        path = cache_dir / cls.key(file_bytes, kind)
        now = time.time()
        if path.exists() and now - path.stat().st_mtime <= cls.MAX_AGE_SECONDS:
            try:
                return load(json.loads(path.read_text(encoding="utf-8")))
            except (OSError, ValueError, TypeError):
                pass

        value = factory()
        try:
            path.write_text(json.dumps(dump(value), ensure_ascii=False), encoding="utf-8")
            files = sorted(cache_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
            for old_path in files[cls.MAX_ENTRIES:]:
                old_path.unlink(missing_ok=True)
        except OSError:
            pass
        return value
