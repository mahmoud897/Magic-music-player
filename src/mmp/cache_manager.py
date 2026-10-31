from __future__ import annotations

import hashlib
import os
import shutil
import time
from pathlib import Path
from typing import Any

from .config import APP_DIR
from .logging_config import get_logger

logger = get_logger("cache")


class AudioCacheManager:
    """Manages an on-disk LRU audio cache for transparent offline playback."""

    def __init__(self, cache_dir: Path | None = None, max_size_bytes: int = 1024 * 1024 * 1024) -> None:
        self.cache_dir = (cache_dir or (APP_DIR / "cache")).resolve()
        self.max_size_bytes = max_size_bytes
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def _hash_key(self, track_id: str) -> str:
        clean = track_id.strip()
        return hashlib.sha256(clean.encode("utf-8")).hexdigest()[:24]

    def get_cached_audio(self, track_id: str) -> Path | None:
        """Return the path to a cached audio file if it exists and is non-empty."""
        if not track_id or track_id.startswith("local:"):
            return None
        key = self._hash_key(track_id)
        matches = list(self.cache_dir.glob(f"{key}.*"))
        for candidate in matches:
            if candidate.is_file() and candidate.stat().st_size > 4096:
                try:
                    os.utime(candidate, None)  # Refresh access timestamp for LRU
                except OSError:
                    pass
                return candidate
        return None

    def get_cache_target(self, track_id: str, ext: str = "m4a") -> Path:
        """Return a target file path for saving newly downloaded or streamed audio."""
        key = self._hash_key(track_id)
        clean_ext = ext.lstrip(".")
        return self.cache_dir / f"{key}.{clean_ext}"

    def put_file(self, track_id: str, source_path: Path) -> Path | None:
        """Store an existing audio file in the cache under this track_id."""
        if not source_path.is_file() or source_path.stat().st_size < 4096:
            return None
        target = self.get_cache_target(track_id, ext=source_path.suffix.lstrip("."))
        try:
            if source_path.resolve() != target.resolve():
                shutil.copy2(source_path, target)
            self.evict_if_needed()
            return target
        except Exception as exc:
            logger.warning("Could not store %s in audio cache: %s", track_id, exc)
            return None

    def evict_if_needed(self) -> int:
        """Enforce maximum cache size by evicting least recently modified files. Returns freed bytes."""
        try:
            files = [f for f in self.cache_dir.iterdir() if f.is_file()]
        except OSError:
            return 0

        total_size = sum(f.stat().st_size for f in files)
        if total_size <= self.max_size_bytes:
            return 0

        # Sort by mtime (oldest first)
        files.sort(key=lambda p: p.stat().st_mtime)
        freed = 0
        for f in files:
            if total_size - freed <= self.max_size_bytes:
                break
            try:
                size = f.stat().st_size
                f.unlink(missing_ok=True)
                freed += size
            except OSError:
                continue
        logger.info("Evicted %d bytes from audio cache", freed)
        return freed

    def clear(self) -> None:
        """Remove all files in the cache."""
        for f in self.cache_dir.glob("*"):
            try:
                if f.is_file():
                    f.unlink()
            except OSError:
                pass

    def stats(self) -> dict[str, Any]:
        """Return cache statistics."""
        try:
            files = [f for f in self.cache_dir.iterdir() if f.is_file()]
            total_bytes = sum(f.stat().st_size for f in files)
            return {
                "count": len(files),
                "total_bytes": total_bytes,
                "total_mb": round(total_bytes / (1024 * 1024), 2),
            }
        except OSError:
            return {"count": 0, "total_bytes": 0, "total_mb": 0.0}
