from __future__ import annotations

import asyncio
import hashlib
import urllib.request
from pathlib import Path
from typing import Callable

from .models import Track

THUMB_DISPLAY_SIZE = 56
THUMB_CACHE_SIZE = THUMB_DISPLAY_SIZE * 2


def cover_resize_box(width: int, height: int, target: int) -> tuple[int, int]:
    """Largest centered square crop box that fits in (width, height)."""
    side = max(1, min(width, height))
    left = (width - side) // 2
    top = (height - side) // 2
    return left, top, left + side, top + side


class ThumbnailService:
    """Lazy album-art loader with a disk cache of Tk-ready PNG files.

    Uses Pillow when available; when it is not installed every request
    resolves to None and the UI shows its placeholder instead.
    """

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        try:
            from PIL import Image  # noqa: F401

            self._pil_ok = True
        except ImportError:
            self._pil_ok = False
        self._memory: dict[str, object] = {}
        self._inflight: set[str] = set()

    def cache_key(self, track: Track) -> str:
        digest = hashlib.sha1(f"{track.source}:{track.id}".encode("utf-8")).hexdigest()[:20]
        return digest

    def cached_png(self, track: Track) -> Path | None:
        if not self._pil_ok or not track.thumbnail_url:
            return None
        path = self.cache_dir / f"{self.cache_key(track)}.png"
        return path if path.exists() else None

    def get_cached_pil(self, key: str) -> object | None:
        return self._memory.get(key)

    def load_sync(self, track: Track) -> Path | None:
        """Blocking fetch+decode+cache. Returns the cached PNG path or None."""
        if not self._pil_ok or not track.thumbnail_url:
            return None
        key = self.cache_key(track)
        path = self.cache_dir / f"{key}.png"
        if path.exists():
            if key not in self._memory:
                try:
                    from PIL import Image

                    self._memory[key] = Image.open(path)
                except Exception:
                    pass
            return path
        try:
            from PIL import Image

            request = urllib.request.Request(track.thumbnail_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = response.read(512_000)
            image = Image.open(__import__("io").BytesIO(payload))
            image = image.convert("RGB")
            image = image.crop(cover_resize_box(image.width, image.height, min(image.size)))
            image = image.resize((THUMB_CACHE_SIZE, THUMB_CACHE_SIZE))
            image.save(path, "PNG")
            self._memory[key] = image
            return path
        except Exception:
            return None

    def load_async(
        self,
        track: Track,
        worker: object,
        on_ready: Callable[[str, Path | None], None],
    ) -> None:
        """Fetch off-thread; on_ready(key, png_path) is scheduled by the caller."""
        if not self._pil_ok or not track.thumbnail_url:
            on_ready(self.cache_key(track), None)
            return
        key = self.cache_key(track)
        if key in self._inflight:
            return
        self._inflight.add(key)

        async def job():
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, self.load_sync, track)
            return key, result

        def done(future) -> None:
            self._inflight.discard(key)
            try:
                resolved_key, path = future.result()
            except Exception:
                resolved_key, path = key, None
            on_ready(resolved_key, path)

        worker.submit(job(), done)
