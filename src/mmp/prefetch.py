from __future__ import annotations

from concurrent.futures import Future
from typing import TYPE_CHECKING

from .logging_config import get_logger

if TYPE_CHECKING:
    from .async_bridge import AsyncWorker
    from .cache_manager import AudioCacheManager
    from .queue_manager import PlaybackQueue
    from .search import StreamExtractor

logger = get_logger("prefetch")


class PrefetchManager:
    """Predictively pre-extracts the upcoming track in the queue to achieve 0ms track transitions."""

    def __init__(
        self,
        queue: PlaybackQueue,
        stream_extractor: StreamExtractor,
        worker: AsyncWorker,
        cache_manager: AudioCacheManager | None = None,
    ) -> None:
        self.queue = queue
        self.stream_extractor = stream_extractor
        self.worker = worker
        self.cache_manager = cache_manager
        self._pending_urls: set[str] = set()

    def check_prefetch(self) -> None:
        """Inspect upcoming track in the queue and trigger background prefetch if needed."""
        next_track = self.queue.peek_next()
        if next_track is None:
            return

        # Skip local files (already 0ms instant)
        if next_track.id.startswith("local:"):
            return

        # Check if already cached on disk
        if self.cache_manager and self.cache_manager.get_cached_audio(next_track.id) is not None:
            return

        # Check if already cached in memory
        if self.stream_extractor.get_cached_stream(next_track.webpage_url) is not None:
            return

        if next_track.webpage_url in self._pending_urls:
            return

        url = next_track.webpage_url
        self._pending_urls.add(url)
        logger.debug("Prefetching stream for upcoming track: %s (%s)", next_track.title, url)

        self.worker.submit(
            self.stream_extractor.get_audio_stream(url),
            lambda future, target_url=url: self._on_prefetch_done(target_url, future),
        )

    def _on_prefetch_done(self, url: str, future: Future) -> None:
        self._pending_urls.discard(url)
        try:
            stream = future.result()
            logger.debug("Successfully prefetched audio stream for %s (valid for %s)", url, stream.expires_at)
        except Exception as exc:
            logger.debug("Prefetch background extraction failed for %s: %s", url, exc)

    def clear(self) -> None:
        self._pending_urls.clear()
