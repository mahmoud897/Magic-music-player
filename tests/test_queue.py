from __future__ import annotations

import pytest

from mmp.models import Track
from mmp.queue_manager import PlaybackQueue, RepeatMode


def make_track(n: int) -> Track:
    return Track(id=f"id{n}", title=f"Song {n}", artist="A", duration=100 + n, source="YouTube", webpage_url=f"u{n}")


@pytest.fixture()
def filled() -> PlaybackQueue:
    queue = PlaybackQueue()
    for n in range(3):
        queue.add(make_track(n))
    return queue


def test_play_now_on_empty_queue_becomes_current() -> None:
    queue = PlaybackQueue()
    track = make_track(1)
    queue.play_now(track)
    assert queue.current == track
    assert len(queue) == 1


def test_play_now_inserts_after_current_and_jumps(filled: PlaybackQueue) -> None:
    filled.jump_to(0)
    special = make_track(99)
    filled.play_now(special)
    assert filled.current == special
    assert filled.advance() == make_track(1)


def test_add_does_not_change_current(filled: PlaybackQueue) -> None:
    assert filled.current is None
    filled.jump_to(0)
    current = filled.current
    filled.add(make_track(50))
    assert filled.current == current
    assert len(filled) == 4


def test_advance_stops_at_end_when_repeat_off(filled: PlaybackQueue) -> None:
    filled.jump_to(2)
    assert filled.advance() is None
    assert filled.current == make_track(2)


def test_advance_wraps_with_repeat_all(filled: PlaybackQueue) -> None:
    filled.set_repeat(RepeatMode.ALL)
    filled.jump_to(2)
    assert filled.advance() == make_track(0)


def test_repeat_one_returns_current_without_moving(filled: PlaybackQueue) -> None:
    filled.set_repeat(RepeatMode.ONE)
    filled.jump_to(1)
    for _ in range(3):
        assert filled.advance() == make_track(1)


def test_step_back_clamps_at_start_and_wraps_on_all(filled: PlaybackQueue) -> None:
    filled.jump_to(0)
    assert filled.step_back() == make_track(0)
    filled.set_repeat(RepeatMode.ALL)
    assert filled.step_back() == make_track(2)


def test_cycle_repeat_progresses_off_all_one(filled: PlaybackQueue) -> None:
    assert filled.repeat_mode == RepeatMode.OFF
    assert filled.cycle_repeat() == RepeatMode.ALL
    assert filled.cycle_repeat() == RepeatMode.ONE
    assert filled.cycle_repeat() == RepeatMode.OFF


def test_remove_before_current_keeps_current(filled: PlaybackQueue) -> None:
    filled.jump_to(2)
    assert filled.remove_at(0) is True
    assert filled.current == make_track(2)
    assert [t.id for t in filled.snapshot().tracks] == ["id1", "id2"]


def test_remove_last_item_clears_queue_state(filled: PlaybackQueue) -> None:
    filled.play_now(make_track(9))
    while len(filled):
        filled.remove_at(0)
    assert filled.current is None
    assert len(filled) == 0


def test_shuffle_keeps_current_then_restores_order(filled: PlaybackQueue) -> None:
    for n in range(10, 15):
        filled.add(make_track(n))
    filled.jump_to(0)
    original = [t.id for t in filled.snapshot().tracks]

    filled.set_shuffle(True)
    assert filled.snapshot().shuffle is True
    assert filled.snapshot().tracks[0].id == original[0]
    shuffled = [t.id for t in filled.snapshot().tracks]
    assert shuffled != original  # 7 upcoming items: collision odds negligible

    filled.set_shuffle(False)
    restored = [t.id for t in filled.snapshot().tracks]
    assert restored == original
    assert filled.current is not None
    assert filled.current.id == original[0]
    assert filled.snapshot().current_index == 0


def test_jump_to_out_of_range_is_noop(filled: PlaybackQueue) -> None:
    assert filled.jump_to(42) is None
    assert filled.jump_to(-1) is None


def test_snapshot_reports_state() -> None:
    queue = PlaybackQueue()
    queue.play_now(make_track(1))
    snapshot = queue.snapshot()
    assert snapshot.tracks == (make_track(1),)
    assert snapshot.current_index == 0
    assert snapshot.repeat == RepeatMode.OFF
    assert snapshot.shuffle is False


def test_add_while_shuffled_randomizes_upcoming() -> None:
    queue = PlaybackQueue()
    queue.play_now(make_track(0))
    queue.set_shuffle(True)
    for n in range(1, 10):
        queue.add(make_track(n))
    upcoming_ids = [t.id for t in queue.snapshot().tracks[1:]]
    assert len(upcoming_ids) == 9
    # Very high probability of not being identical to sequential 1..9
    assert upcoming_ids != [f"id{n}" for n in range(1, 10)]


def test_advance_ignore_repeat_one() -> None:
    queue = PlaybackQueue()
    queue.add(make_track(0))
    queue.add(make_track(1))
    queue.jump_to(0)
    queue.set_repeat(RepeatMode.ONE)
    # Default advance stays on current
    assert queue.advance(ignore_repeat_one=False) == make_track(0)
    # Skip / manual next moves forward
    assert queue.advance(ignore_repeat_one=True) == make_track(1)


def test_advance_wraps_and_reshuffles_when_repeat_all_and_shuffle() -> None:
    queue = PlaybackQueue()
    for n in range(10):
        queue.add(make_track(n))
    queue.jump_to(9)
    queue.set_shuffle(True)
    queue.set_repeat(RepeatMode.ALL)
    wrapped = queue.advance()
    assert wrapped is not None
    assert queue.snapshot().current_index == 0


def test_unshuffle_after_advancing_preserves_history_and_restores_tail() -> None:
    queue = PlaybackQueue()
    for n in range(6):
        queue.add(make_track(n))
    queue.jump_to(0)
    queue.set_shuffle(True)
    # Advance twice
    queue.advance()
    queue.advance()
    current = queue.current
    assert current is not None
    queue.set_shuffle(False)
    assert queue.current == current
    tail_tracks = queue.snapshot().tracks[queue.snapshot().current_index + 1 :]
    tail_ids = [int(t.id.replace("id", "")) for t in tail_tracks]
    assert tail_ids == sorted(tail_ids)

