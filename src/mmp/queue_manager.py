from __future__ import annotations

import random
from dataclasses import dataclass
from enum import Enum

from .models import Track


class RepeatMode(Enum):
    OFF = "off"
    ALL = "all"
    ONE = "one"


@dataclass(frozen=True, slots=True)
class QueueSnapshot:
    tracks: tuple[Track, ...]
    current_index: int
    repeat: RepeatMode
    shuffle: bool


class PlaybackQueue:
    """In-memory playback queue with shuffle, repeat modes, and jump support."""

    def __init__(self) -> None:
        self._tracks: list[Track] = []
        self._order: list[int] = []
        self._pos = -1
        self.repeat_mode = RepeatMode.OFF
        self.shuffle = False
        self._rng = random.Random()

    def __len__(self) -> int:
        return len(self._order)

    @property
    def current(self) -> Track | None:
        if 0 <= self._pos < len(self._order):
            return self._tracks[self._order[self._pos]]
        return None

    def play_now(self, track: Track) -> None:
        """Insert the track right after the current one and make it current."""
        if not self._order:
            self._tracks.append(track)
            self._order.append(len(self._tracks) - 1)
            self._pos = 0
            return
        self._tracks.append(track)
        insert_at = min(self._pos + 1, len(self._order))
        self._order.insert(insert_at, len(self._tracks) - 1)
        self._pos += 1

    def play_next(self, track: Track) -> None:
        """Insert the track to be played right after the current one."""
        if not self._order:
            self.play_now(track)
            return
        self._tracks.append(track)
        insert_at = min(self._pos + 1, len(self._order))
        self._order.insert(insert_at, len(self._tracks) - 1)

    def add(self, track: Track) -> None:
        idx = len(self._tracks)
        self._tracks.append(track)
        if self.shuffle and len(self._order) > max(0, self._pos + 1):
            insert_at = self._rng.randint(max(0, self._pos + 1), len(self._order))
            self._order.insert(insert_at, idx)
        else:
            self._order.append(idx)

    def peek_next(self) -> Track | None:
        """Inspect the upcoming track honoring repeat mode without advancing position."""
        if not self._order:
            return None
        if self._pos < 0:
            return self._tracks[self._order[0]]
        if self.repeat_mode == RepeatMode.ONE:
            return self.current
        if self._pos + 1 < len(self._order):
            return self._tracks[self._order[self._pos + 1]]
        if self.repeat_mode == RepeatMode.ALL:
            return self._tracks[self._order[0]]
        return None

    def peek_previous(self) -> Track | None:
        """Inspect the previous track honoring repeat mode without changing position."""
        if not self._order:
            return None
        if self._pos <= 0:
            if self.repeat_mode == RepeatMode.ALL and len(self._order) > 1:
                return self._tracks[self._order[len(self._order) - 1]]
            return self._tracks[self._order[0]] if self._order else None
        return self._tracks[self._order[self._pos - 1]]

    def advance(self, ignore_repeat_one: bool = False) -> Track | None:
        """Move to the next track honoring repeat mode; None when playback should stop."""
        if not self._order:
            return None
        if self._pos < 0:
            self._pos = 0
            return self.current
        if self.repeat_mode == RepeatMode.ONE and not ignore_repeat_one:
            return self.current
        if self._pos + 1 < len(self._order):
            self._pos += 1
            return self.current
        if self.repeat_mode == RepeatMode.ALL:
            self._pos = 0
            if self.shuffle and len(self._order) > 1:
                tail = list(self._order)
                self._rng.shuffle(tail)
                self._order = tail
            return self.current
        return None

    def step_back(self) -> Track | None:
        if not self._order:
            return None
        if self._pos <= 0:
            if self.repeat_mode == RepeatMode.ALL and len(self._order) > 1:
                self._pos = len(self._order) - 1
            else:
                self._pos = 0
            return self.current
        self._pos -= 1
        return self.current

    def jump_to(self, play_index: int) -> Track | None:
        if 0 <= play_index < len(self._order):
            self._pos = play_index
            return self.current
        return None

    def remove_at(self, play_index: int) -> bool:
        if not (0 <= play_index < len(self._order)):
            return False
        removed_orig = self._order.pop(play_index)
        del self._tracks[removed_orig]
        self._order = [i if i < removed_orig else i - 1 for i in self._order]
        if play_index < self._pos:
            self._pos -= 1
        elif play_index == self._pos:
            self._pos = min(self._pos, len(self._order) - 1) if self._order else -1
        if not self._order:
            self._pos = -1
        return True

    def set_shuffle(self, enabled: bool) -> None:
        if enabled == self.shuffle:
            return
        self.shuffle = enabled
        if not self._order:
            return
        current_orig = self._order[self._pos] if self._pos >= 0 else None
        if enabled:
            head = self._order[: self._pos + 1] if self._pos >= 0 else []
            tail = self._order[self._pos + 1 :] if self._pos >= 0 else list(self._order)
            self._rng.shuffle(tail)
            self._order = head + tail
        else:
            head = self._order[: self._pos + 1] if self._pos >= 0 else []
            tail = self._order[self._pos + 1 :] if self._pos >= 0 else list(self._order)
            tail.sort()
            self._order = head + tail
        if current_orig is not None and current_orig in self._order:
            self._pos = self._order.index(current_orig)
        elif not self._order:
            self._pos = -1

    def set_repeat(self, mode: RepeatMode) -> None:
        self.repeat_mode = mode

    def cycle_repeat(self) -> RepeatMode:
        cycle = (RepeatMode.OFF, RepeatMode.ALL, RepeatMode.ONE)
        self.repeat_mode = cycle[(cycle.index(self.repeat_mode) + 1) % len(cycle)]
        return self.repeat_mode

    def clear(self) -> None:
        self._tracks.clear()
        self._order.clear()
        self._pos = -1

    def snapshot(self) -> QueueSnapshot:
        return QueueSnapshot(
            tracks=tuple(self._tracks[i] for i in self._order),
            current_index=self._pos,
            repeat=self.repeat_mode,
            shuffle=self.shuffle,
        )
