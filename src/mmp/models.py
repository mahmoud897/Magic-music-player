from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Track:
    id: str
    title: str
    artist: str
    duration: int | None
    source: str
    webpage_url: str
    thumbnail_url: str | None = None

    @property
    def duration_label(self) -> str:
        if self.duration is None:
            return "--:--"
        minutes, seconds = divmod(int(max(0, self.duration)), 60)
        hours, minutes = divmod(minutes, 60)
        if hours:
            return f"{hours}:{minutes:02d}:{seconds:02d}"
        return f"{minutes}:{seconds:02d}"
