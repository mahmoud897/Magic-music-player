from __future__ import annotations

import json
import logging
import sqlite3
import time
from pathlib import Path

from .logging_config import get_logger
from .models import Track

logger = get_logger("library")
HISTORY_CAP = 200


class MusicLibrary:
    """Small SQLite-backed store for favorites, play history, and settings."""

    def __init__(self, db_path: Path) -> None:
        db_path = Path(db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        try:
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.execute("PRAGMA busy_timeout = 5000")
            self._conn.execute("PRAGMA synchronous = NORMAL")
        except sqlite3.Error as exc:
            logger.warning("Could not set performance pragmas on %s: %s", db_path, exc)
        self._init_schema()
        self._cached_favorite_ids: set[str] = {
            row["track_id"] for row in self._conn.execute("SELECT track_id FROM favorites")
        }
        self._cached_settings: dict[str, str] = {}
        for row in self._conn.execute("SELECT key, value FROM kv"):
            if row["value"] is not None:
                self._cached_settings[row["key"]] = str(row["value"])

    def _init_schema(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tracks (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                artist TEXT NOT NULL DEFAULT '',
                duration INTEGER,
                source TEXT NOT NULL DEFAULT '',
                webpage_url TEXT NOT NULL UNIQUE
            );
            CREATE TABLE IF NOT EXISTS favorites (
                track_id TEXT PRIMARY KEY REFERENCES tracks(id) ON DELETE CASCADE,
                added_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS play_history (
                entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
                track_id TEXT NOT NULL REFERENCES tracks(id) ON DELETE CASCADE,
                played_at REAL NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_history_played ON play_history(played_at DESC);
            CREATE TABLE IF NOT EXISTS kv (
                key TEXT PRIMARY KEY,
                value TEXT
            );
            """
        )
        self._conn.commit()

    def upsert_track(self, track: Track) -> None:
        with self._conn:
            self._conn.execute(
                "INSERT INTO tracks (id, title, artist, duration, source, webpage_url) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET "
                "title=excluded.title, artist=excluded.artist, duration=excluded.duration",
                (track.id, track.title, track.artist, track.duration, track.source, track.webpage_url),
            )

    def set_favorite(self, track: Track, favorite: bool) -> None:
        if favorite:
            self._cached_favorite_ids.add(track.id)
            self.upsert_track(track)
            with self._conn:
                self._conn.execute(
                    "INSERT OR IGNORE INTO favorites (track_id, added_at) VALUES (?, ?)",
                    (track.id, time.time()),
                )
        else:
            self._cached_favorite_ids.discard(track.id)
            with self._conn:
                self._conn.execute("DELETE FROM favorites WHERE track_id = ?", (track.id,))

    def is_favorite(self, track_id: str) -> bool:
        return track_id in self._cached_favorite_ids

    def favorite_ids(self) -> set[str]:
        return set(self._cached_favorite_ids)

    def _tracks_from_rows(self, rows) -> list[Track]:
        return [
            Track(
                id=row["id"],
                title=row["title"],
                artist=row["artist"],
                duration=row["duration"],
                source=row["source"],
                webpage_url=row["webpage_url"],
            )
            for row in rows
        ]

    def favorites(self) -> list[Track]:
        rows = self._conn.execute(
            "SELECT t.* FROM favorites f JOIN tracks t ON t.id = f.track_id ORDER BY f.added_at DESC"
        ).fetchall()
        return self._tracks_from_rows(rows)

    def record_play(self, track: Track) -> None:
        self.upsert_track(track)
        with self._conn:
            self._conn.execute(
                "INSERT INTO play_history (track_id, played_at) VALUES (?, ?)", (track.id, time.time())
            )
            self._conn.execute(
                "DELETE FROM play_history WHERE entry_id NOT IN ("
                "SELECT entry_id FROM play_history ORDER BY played_at DESC LIMIT ?)",
                (HISTORY_CAP,),
            )

    def recent_plays(self, limit: int = 50) -> list[Track]:
        rows = self._conn.execute(
            "SELECT t.* FROM tracks t "
            "JOIN ("
            "    SELECT track_id, MAX(played_at) AS latest_play "
            "    FROM play_history "
            "    GROUP BY track_id"
            ") h ON t.id = h.track_id "
            "ORDER BY h.latest_play DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return self._tracks_from_rows(rows)

    def get_setting(self, key: str, default: str | None = None) -> str | None:
        if key in self._cached_settings:
            return self._cached_settings[key]
        row = self._conn.execute("SELECT value FROM kv WHERE key = ?", (key,)).fetchone()
        if row is None or row["value"] is None:
            return default
        val = str(row["value"])
        self._cached_settings[key] = val
        return val

    def set_setting(self, key: str, value: str) -> None:
        val_str = str(value)
        self._cached_settings[key] = val_str
        with self._conn:
            self._conn.execute(
                "INSERT INTO kv (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, val_str),
            )

    def save_session(self, queue_tracks: list[Track], current_index: int, position: float) -> None:
        """Persist active queue, current index, and track playback position."""
        payload = {
            "tracks": [
                {
                    "id": t.id,
                    "title": t.title,
                    "artist": t.artist,
                    "duration": t.duration,
                    "source": t.source,
                    "webpage_url": t.webpage_url,
                    "thumbnail_url": t.thumbnail_url,
                }
                for t in queue_tracks
            ],
            "current_index": current_index,
            "position": position,
        }
        self.set_setting("session_restore", json.dumps(payload))

    def load_session(self) -> dict | None:
        """Retrieve persisted session state snapshot."""
        raw = self.get_setting("session_restore")
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error as exc:
            logger.warning("Error closing database: %s", exc)
