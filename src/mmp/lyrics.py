from __future__ import annotations

import asyncio
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING

from .logging_config import get_logger

if TYPE_CHECKING:
    from .models import Track

logger = get_logger("lyrics")

LRC_TIMESTAMP_RE = re.compile(r"\[(\d+):(\d+(?:\.\d+)?)\](.*)")


@dataclass(frozen=True, slots=True)
class LyricLine:
    timestamp: float
    text: str


@dataclass(slots=True)
class LyricsData:
    synced: list[LyricLine]
    plain: str | None = None

    @property
    def has_lyrics(self) -> bool:
        return bool(self.synced or self.plain)


def clean_song_metadata(title: str, artist: str) -> tuple[str, str]:
    """Strip common YouTube noise like '(Official Video)', '[4K]', feat. artists."""
    clean_title = title
    clean_artist = artist

    # Remove (Official Video), [Official Audio], etc.
    clean_title = re.sub(
        r"[\(\[](?:official|video|audio|lyrics|music video|hd|4k|remastered|visualizer).*?[\)\]]",
        "",
        clean_title,
        flags=re.IGNORECASE,
    )

    # Split 'Artist - Title' if present
    if " - " in clean_title:
        parts = clean_title.split(" - ", 1)
        clean_artist = parts[0].strip()
        clean_title = parts[1].strip()

    # Strip leftover trailing punctuation
    clean_title = clean_title.strip(" -_()[]")
    clean_artist = clean_artist.strip(" -_()[]")

    return clean_title or title, clean_artist or artist


def parse_lrc(lrc_text: str) -> list[LyricLine]:
    """Parse standard LRC format string into sorted LyricLine objects."""
    lines: list[LyricLine] = []
    for raw_line in lrc_text.splitlines():
        match = LRC_TIMESTAMP_RE.match(raw_line.strip())
        if match:
            minutes = int(match.group(1))
            seconds = float(match.group(2))
            text = match.group(3).strip()
            total_seconds = minutes * 60 + seconds
            lines.append(LyricLine(timestamp=total_seconds, text=text))
    lines.sort(key=lambda item: item.timestamp)
    return lines


class LyricsService:
    """Fetches real-time synchronized karaoke lyrics from LRCLIB."""

    def __init__(self) -> None:
        self._cache: dict[str, LyricsData] = {}
        self._inflight: dict[str, asyncio.Task[LyricsData]] = {}

    async def get_lyrics(self, track: Track) -> LyricsData:
        if track.id in self._cache:
            return self._cache[track.id]

        task = self._inflight.get(track.id)
        if task is None:
            task = asyncio.create_task(self._load_lyrics(track))
            self._inflight[track.id] = task
            task.add_done_callback(lambda completed, track_id=track.id: self._clear_inflight(track_id, completed))
        return await asyncio.shield(task)

    async def _load_lyrics(self, track: Track) -> LyricsData:
        loop = asyncio.get_running_loop()
        data = await loop.run_in_executor(None, partial(self._fetch_sync, track))
        self._cache[track.id] = data
        return data

    def _clear_inflight(self, track_id: str, completed: asyncio.Task[LyricsData]) -> None:
        if self._inflight.get(track_id) is completed:
            self._inflight.pop(track_id, None)

    def _fetch_sync(self, track: Track) -> LyricsData:
        title, artist = clean_song_metadata(track.title, track.artist)
        params = {
            "track_name": title,
            "artist_name": artist,
        }
        if track.duration:
            params["duration"] = str(int(track.duration))

        url = f"https://lrclib.net/api/get?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "MagicMusicPlayer/1.0 (https://github.com/magic-music-player)",
                "Accept": "application/json",
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=4.0) as resp:
                if resp.status == 200:
                    payload = json.loads(resp.read().decode("utf-8"))
                    synced_raw = payload.get("syncedLyrics")
                    plain_raw = payload.get("plainLyrics")
                    synced = parse_lrc(synced_raw) if synced_raw else []
                    return LyricsData(synced=synced, plain=plain_raw)
        except Exception as exc:
            logger.debug("Direct lyrics fetch failed: %s; trying search fallback", exc)

        # Fallback to search endpoint
        search_query = f"{title} {artist}".strip()
        search_url = f"https://lrclib.net/api/search?{urllib.parse.urlencode({'q': search_query})}"
        search_req = urllib.request.Request(
            search_url,
            headers={
                "User-Agent": "MagicMusicPlayer/1.0",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(search_req, timeout=4.0) as resp:
                if resp.status == 200:
                    results = json.loads(resp.read().decode("utf-8"))
                    if isinstance(results, list) and results:
                        first = results[0]
                        synced_raw = first.get("syncedLyrics")
                        plain_raw = first.get("plainLyrics")
                        synced = parse_lrc(synced_raw) if synced_raw else []
                        return LyricsData(synced=synced, plain=plain_raw)
        except Exception as exc:
            logger.debug("Lyrics search fallback also failed: %s", exc)

        return LyricsData(synced=[], plain=None)

    def find_active_line_index(self, lines: list[LyricLine], position_seconds: float) -> int:
        """Binary/linear search for the active lyric line at current playback position."""
        if not lines:
            return -1
        active = -1
        for index, line in enumerate(lines):
            if line.timestamp <= position_seconds:
                active = index
            else:
                break
        return active
