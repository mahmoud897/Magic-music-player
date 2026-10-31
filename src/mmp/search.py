from __future__ import annotations

import asyncio
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from functools import partial
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, urlparse

from yt_dlp import YoutubeDL

from .logging_config import get_logger
from .models import Track

logger = get_logger("search")


YDL_BASE_OPTIONS: dict[str, Any] = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extract_flat": "in_playlist",
    "noplaylist": True,
    "socket_timeout": 4.5,
    "source_address": "0.0.0.0",
    "check_formats": None,
    "ignoreerrors": True,
    "cachedir": False,
    "youtube_include_dash_manifest": False,
    "youtube_include_hls_manifest": False,
    "writesubtitles": False,
    "writeautomaticsub": False,
    "allsubtitles": False,
    "writeinfojson": False,
}


@dataclass(frozen=True, slots=True)
class ProviderSearchStatus:
    provider: str
    state: str
    duration_seconds: float
    result_count: int = 0
    error: str | None = None


def pick_thumbnail(entry: dict[str, Any]) -> str | None:
    """Choose a compact thumbnail URL from a yt-dlp flat entry."""
    for key in ("thumbnail", "artwork_url"):
        url = entry.get(key)
        if isinstance(url, str) and url.startswith("http"):
            return url
    candidates = []
    for item in entry.get("thumbnails") or []:
        if not isinstance(item, dict) or not isinstance(item.get("url"), str):
            continue
        width = item.get("width") or 9999
        if isinstance(width, (int, float)) and 100 <= width <= 640:
            candidates.append((width, item["url"]))
    if candidates:
        return min(candidates)[1]
    fallbacks = [item["url"] for item in entry.get("thumbnails") or [] if isinstance(item, dict) and item.get("url")]
    return fallbacks[-1] if fallbacks else None


def is_direct_url(query: str) -> bool:
    """Detect whether a query is a direct media or streaming link (e.g. YouTube, SoundCloud)."""
    clean = query.strip()
    if (
        clean.startswith("www.")
        or clean.startswith("youtu.be/")
        or clean.startswith("youtube.com/")
        or clean.startswith("music.youtube.com/")
        or clean.startswith("soundcloud.com/")
    ):
        clean = "https://" + clean
    if not (clean.startswith("http://") or clean.startswith("https://")):
        return False
    try:
        parsed = urlparse(clean)
        return bool(parsed.scheme in ("http", "https") and parsed.netloc)
    except Exception:
        return False


class SearchService:
    def __init__(self, limit_per_source: int = 6, cache_size: int = 32, cache_ttl: float = 900.0) -> None:
        self.limit_per_source = limit_per_source
        self.cache_size = max(1, cache_size)
        self.cache_ttl = max(0.0, cache_ttl)
        self._search_cache: OrderedDict[str, tuple[float, list[Track]]] = OrderedDict()
        self._cache_lock = threading.Lock()

    @staticmethod
    def _cache_key(query: str) -> str:
        return " ".join(query.split()).casefold()

    def get_cached_search(self, query: str) -> list[Track] | None:
        """Return a fresh result snapshot so repeated searches can paint immediately."""
        key = self._cache_key(query)
        if not key or self.cache_ttl <= 0:
            return None
        now = time.monotonic()
        with self._cache_lock:
            cached = self._search_cache.get(key)
            if cached is None:
                return None
            created_at, tracks = cached
            if now - created_at >= self.cache_ttl:
                self._search_cache.pop(key, None)
                return None
            self._search_cache.move_to_end(key)
            return list(tracks)

    def _remember_search(self, query: str, tracks: list[Track]) -> None:
        key = self._cache_key(query)
        if not key or not tracks or self.cache_ttl <= 0:
            return
        with self._cache_lock:
            self._search_cache[key] = (time.monotonic(), list(tracks))
            self._search_cache.move_to_end(key)
            while len(self._search_cache) > self.cache_size:
                self._search_cache.popitem(last=False)

    async def search(
        self,
        query: str,
        *,
        refresh: bool = False,
        on_partial: Callable[[list[Track]], None] | None = None,
        on_provider_status: Callable[[ProviderSearchStatus], None] | None = None,
    ) -> list[Track]:
        clean_query = query.strip()
        if not clean_query:
            return []
        if not refresh:
            cached = self.get_cached_search(clean_query)
            if cached is not None:
                return cached

        if (
            clean_query.startswith("www.")
            or clean_query.startswith("youtu.be/")
            or clean_query.startswith("youtube.com/")
            or clean_query.startswith("music.youtube.com/")
            or clean_query.startswith("soundcloud.com/")
        ):
            clean_query = "https://" + clean_query

        if is_direct_url(clean_query):
            started = time.monotonic()
            loop = asyncio.get_running_loop()
            try:
                tracks = await loop.run_in_executor(None, partial(self._extract_direct_url, clean_query))
            except Exception as exc:
                if on_provider_status is not None:
                    on_provider_status(
                        ProviderSearchStatus(
                            provider="Direct Link",
                            state="failed",
                            duration_seconds=time.monotonic() - started,
                            error=str(exc),
                        )
                    )
                return []
            source = tracks[0].source if tracks else "Direct Link"
            if on_provider_status is not None:
                on_provider_status(
                    ProviderSearchStatus(
                        provider=source,
                        state="done",
                        duration_seconds=time.monotonic() - started,
                        result_count=len(tracks),
                    )
                )
            if tracks and on_partial is not None:
                on_partial(tracks)
            self._remember_search(clean_query, tracks)
            return tracks

        sources = [
            (f"ytsearch{self.limit_per_source}:{clean_query}", "YouTube"),
            (f"ytsearch{self.limit_per_source}:{clean_query} audio", "YouTube Music"),
            (f"scsearch{self.limit_per_source}:{clean_query}", "SoundCloud"),
        ]
        completed: dict[int, list[Track]] = {}

        async def collect(index: int, url: str, source: str) -> None:
            started = time.monotonic()
            try:
                result = await self._search_source(url, source)
            except Exception as exc:
                status = ProviderSearchStatus(
                    provider=source,
                    state="failed",
                    duration_seconds=time.monotonic() - started,
                    error=str(exc),
                )
                if on_provider_status is not None:
                    try:
                        on_provider_status(status)
                    except Exception:
                        logger.debug("Ignoring provider-status callback failure", exc_info=True)
                return
            completed[index] = result
            if on_provider_status is not None:
                status = ProviderSearchStatus(
                    provider=source,
                    state="done",
                    duration_seconds=time.monotonic() - started,
                    result_count=len(result),
                )
                try:
                    on_provider_status(status)
                except Exception:
                    logger.debug("Ignoring provider-status callback failure", exc_info=True)
            if result and on_partial is not None:
                partial = self._merge_results(completed)
                try:
                    on_partial(partial)
                except Exception:
                    logger.debug("Ignoring search partial-result callback failure", exc_info=True)

        await asyncio.gather(*(collect(i, url, source) for i, (url, source) in enumerate(sources)))
        tracks = self._merge_results(completed)
        self._remember_search(clean_query, tracks)
        return tracks

    def _merge_results(self, completed: dict[int, list[Track]]) -> list[Track]:
        tracks: list[Track] = []
        seen_urls: set[str] = set()
        for index in sorted(completed):
            result = completed[index]
            for track in result:
                if track.webpage_url in seen_urls:
                    continue
                tracks.append(track)
                seen_urls.add(track.webpage_url)
        return tracks[: self.limit_per_source * 3]

    async def get_related_tracks(self, track: Track, limit: int = 8) -> list[Track]:
        """Fetch similar / radio tracks based on the provided track."""
        if not track:
            return []
        query_term = f"{track.artist} audio" if track.artist else f"{track.title} radio"
        tracks = await self._search_source(f"ytsearch{limit}:{query_term}", "Radio")
        return [t for t in tracks if t.id != track.id and t.webpage_url != track.webpage_url]

    async def _search_source(self, url: str, source: str) -> list[Track]:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(self._extract_search, url, source))

    def _extract_search(self, url: str, source: str) -> list[Track]:
        with YoutubeDL(YDL_BASE_OPTIONS) as ydl:
            data = ydl.extract_info(url, download=False)

        entries = data.get("entries") or []
        tracks: list[Track] = []
        for entry in entries:
            webpage_url = entry.get("webpage_url") or entry.get("url") or ""
            if webpage_url and not webpage_url.startswith("http") and source.startswith("YouTube"):
                webpage_url = f"https://www.youtube.com/watch?v={webpage_url}"
            if not webpage_url:
                continue
            title = entry.get("title") or "Unknown title"
            artist = entry.get("uploader") or entry.get("channel") or entry.get("artist") or "Unknown"
            tracks.append(
                Track(
                    id=str(entry.get("id") or webpage_url),
                    title=title,
                    artist=artist,
                    duration=entry.get("duration"),
                    source=source,
                    webpage_url=webpage_url,
                    thumbnail_url=pick_thumbnail(entry),
                )
            )
        return tracks

    def _extract_direct_url(self, url: str) -> list[Track]:
        opts = dict(YDL_BASE_OPTIONS)
        with YoutubeDL(opts) as ydl:
            data = ydl.extract_info(url, download=False)
        if not data:
            return []

        entries = data.get("entries")
        raw_items = list(entries) if entries is not None else [data]

        parsed = urlparse(url)
        netloc = parsed.netloc.lower()
        if "soundcloud.com" in netloc:
            default_source = "SoundCloud"
        elif "music.youtube.com" in netloc:
            default_source = "YouTube Music"
        elif "youtube.com" in netloc or "youtu.be" in netloc:
            default_source = "YouTube"
        else:
            default_source = data.get("extractor_key") or "Web"

        tracks: list[Track] = []
        for entry in raw_items:
            if not isinstance(entry, dict):
                continue
            webpage_url = entry.get("webpage_url") or entry.get("url") or url
            if webpage_url and not webpage_url.startswith("http") and "youtube" in default_source.lower():
                webpage_url = f"https://www.youtube.com/watch?v={webpage_url}"
            title = entry.get("title") or "Direct Stream"
            artist = entry.get("uploader") or entry.get("channel") or entry.get("artist") or "Direct"
            tracks.append(
                Track(
                    id=str(entry.get("id") or webpage_url),
                    title=title,
                    artist=artist,
                    duration=entry.get("duration"),
                    source=default_source,
                    webpage_url=webpage_url,
                    thumbnail_url=pick_thumbnail(entry),
                )
            )
        return tracks


@dataclass(frozen=True, slots=True)
class AudioStream:
    """A direct audio stream URL plus the HTTP headers required to fetch it.

    YouTube IP-locks and UA-checks its media URLs; without the User-Agent
    (and sometimes Cookie/Referer) reported by yt-dlp, servers answer 403.
    """

    url: str
    headers: dict[str, str] = field(default_factory=dict)
    extracted_at: float = field(default_factory=time.time)
    expires_at: float | None = None

    def is_expired(self, buffer_seconds: float = 60.0) -> bool:
        now = time.time()
        if self.expires_at is not None:
            return (now + buffer_seconds) >= self.expires_at
        # Default fallback: YouTube URLs expire in ~6 hours; assume 5 hours safe window
        return (now - self.extracted_at) > (5 * 3600 - buffer_seconds)


class StreamExtractor:
    def __init__(self) -> None:
        self._stream_cache: dict[str, AudioStream] = {}

    def get_cached_stream(self, webpage_url: str) -> AudioStream | None:
        """Return non-expired cached stream if available."""
        if webpage_url in self._stream_cache:
            stream = self._stream_cache[webpage_url]
            if not stream.is_expired():
                return stream
            self._stream_cache.pop(webpage_url, None)
        return None

    def cache_stream(self, webpage_url: str, stream: AudioStream) -> None:
        self._stream_cache[webpage_url] = stream

    def clear_cache(self) -> None:
        self._stream_cache.clear()

    async def get_audio_stream(self, webpage_url: str) -> AudioStream:
        # Fast path 1: local downloaded files bypass scraping completely (0ms)
        if webpage_url.startswith("local:"):
            local_path = webpage_url[6:]
            return AudioStream(url=local_path, headers={})
        if not webpage_url.startswith("http://") and not webpage_url.startswith("https://"):
            candidate = Path(webpage_url)
            if candidate.is_file():
                return AudioStream(url=str(candidate), headers={})

        # Fast path 2: in-memory cache hit
        cached = self.get_cached_stream(webpage_url)
        if cached is not None:
            logger.debug("In-memory stream cache hit for %s", webpage_url)
            return cached

        loop = asyncio.get_running_loop()
        stream = await loop.run_in_executor(None, partial(self._extract_audio_stream, webpage_url))
        self._stream_cache[webpage_url] = stream
        return stream

    async def get_audio_stream_url(self, webpage_url: str) -> str:
        stream = await self.get_audio_stream(webpage_url)
        return stream.url

    def _extract_audio_stream(self, webpage_url: str) -> AudioStream:
        options = {
            **YDL_BASE_OPTIONS,
            "extract_flat": False,
            "format": "bestaudio[ext=m4a]/bestaudio[acodec^=opus]/bestaudio/best",
            "playlist_items": "1",
        }
        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(webpage_url, download=False)
        stream_url = info.get("url")
        if not stream_url:
            raise RuntimeError("Could not extract a playable audio stream URL.")
        headers = {str(k): str(v) for k, v in (info.get("http_headers") or {}).items()}

        expires_at: float | None = None
        try:
            parsed = urlparse(stream_url)
            qs = parse_qs(parsed.query)
            if "expire" in qs:
                expires_at = float(qs["expire"][0])
        except Exception as exc:
            logger.debug("Could not parse expire timestamp from stream url: %s", exc)

        return AudioStream(url=stream_url, headers=headers, expires_at=expires_at)

