from __future__ import annotations

import asyncio
from concurrent.futures import Future

from mmp.models import Track
from mmp.prefetch import PrefetchManager
from mmp.queue_manager import PlaybackQueue, RepeatMode
from mmp.search import AudioStream, StreamExtractor


class DummyWorker:
    def __init__(self) -> None:
        self.submitted_coros: list = []

    def submit(self, coro, callback=None):
        self.submitted_coros.append(coro)
        fut = Future()
        fut.set_result(AudioStream(url="http://prefetched/audio.opus"))
        if callback:
            callback(fut)
        # Close coro to avoid warnings
        try:
            coro.close()
        except Exception:
            pass
        return fut


def test_queue_peek_methods() -> None:
    queue = PlaybackQueue()
    t1 = Track(id="1", title="Song 1", artist="A", duration=100, source="YT", webpage_url="http://1")
    t2 = Track(id="2", title="Song 2", artist="A", duration=100, source="YT", webpage_url="http://2")
    t3 = Track(id="3", title="Song 3", artist="A", duration=100, source="YT", webpage_url="http://3")

    assert queue.peek_next() is None
    assert queue.peek_previous() is None

    queue.add(t1)
    queue.add(t2)
    queue.add(t3)

    # Initial state, pos = -1
    assert queue.peek_next() == t1

    queue.advance()  # pos = 0 (t1)
    assert queue.current == t1
    assert queue.peek_next() == t2
    assert queue.peek_previous() == t1

    queue.advance()  # pos = 1 (t2)
    assert queue.peek_next() == t3
    assert queue.peek_previous() == t1

    queue.advance()  # pos = 2 (t3)
    assert queue.peek_next() is None
    assert queue.peek_previous() == t2

    # Repeat ALL mode
    queue.set_repeat(RepeatMode.ALL)
    assert queue.peek_next() == t1
    assert queue.peek_previous() == t2

    # Repeat ONE mode
    queue.set_repeat(RepeatMode.ONE)
    assert queue.peek_next() == t3


def test_prefetch_manager_triggers_on_upcoming() -> None:
    queue = PlaybackQueue()
    t1 = Track(id="1", title="Song 1", artist="A", duration=100, source="YT", webpage_url="http://1")
    t2 = Track(id="2", title="Song 2", artist="A", duration=100, source="YT", webpage_url="http://2")
    queue.add(t1)
    queue.add(t2)
    queue.advance()  # playing t1, upcoming is t2

    extractor = StreamExtractor()
    worker = DummyWorker()
    prefetch = PrefetchManager(queue, extractor, worker)

    # Check prefetch triggers background job
    prefetch.check_prefetch()
    assert len(worker.submitted_coros) == 1

    # If stream is already cached, check_prefetch will not re-submit
    extractor.cache_stream(t2.webpage_url, AudioStream(url="http://cached", expires_at=9999999999))
    prefetch.check_prefetch()
    assert len(worker.submitted_coros) == 1
