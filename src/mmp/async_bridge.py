from __future__ import annotations

import asyncio
import threading
from collections.abc import Awaitable, Callable
from concurrent.futures import Future
from typing import TypeVar


T = TypeVar("T")


class AsyncWorker:
    """Runs network-heavy asyncio work away from Tk's main thread."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name="mmp-async", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def submit(self, coro: Awaitable[T], callback: Callable[[Future[T]], None] | None = None) -> Future[T]:
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        if callback is not None:
            future.add_done_callback(callback)
        return future

    def stop(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
