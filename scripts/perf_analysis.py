"""Deterministic search and tab-render benchmark for the local desktop app.

The default run uses fixed local provider fixtures and never contacts a service.
Add --live to issue one real search (six results per provider at most).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import shutil
import statistics
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = PROJECT_ROOT / "src"
if str(SOURCE_ROOT) not in sys.path:
    sys.path.insert(0, str(SOURCE_ROOT))


def _install_sandbox_safe_asyncio_loop() -> None:
    """Avoid the restricted Windows localhost socketpair, polling at 10 ms."""
    from asyncio.proactor_events import BaseProactorEventLoop

    class NoSocket:
        def fileno(self) -> int:
            return -1

        def close(self) -> None:
            pass

        def send(self, _data: bytes) -> None:
            pass

    def make_self_pipe(loop) -> None:
        loop._ssock = NoSocket()
        loop._csock = NoSocket()
        loop._internal_fds += 1
        original_select = loop._proactor.select
        loop._proactor.select = lambda timeout=None: original_select(
            0.01 if timeout is None else min(timeout, 0.01)
        )

    BaseProactorEventLoop._make_self_pipe = make_self_pipe
    BaseProactorEventLoop._write_to_self = lambda _loop: None
    BaseProactorEventLoop._loop_self_reading = lambda _loop: None


def _summary(values: list[float]) -> dict[str, float | int]:
    ordered = sorted(values)
    return {
        "n": len(ordered),
        "median_ms": round(statistics.median(ordered), 3),
        "p95_ms": round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 3),
    }


def _track(track_id: str, provider: str, number: int):
    from mmp.models import Track

    return Track(
        id=f"{provider}-{track_id}-{number}",
        title=f"Benchmark track {number}",
        artist="Local benchmark",
        duration=180,
        source=provider,
        webpage_url=f"https://example.invalid/{provider}/{track_id}/{number}",
    )


def _tracks(count: int, prefix: str):
    from mmp.models import Track

    return [
        Track(
            id=f"{prefix}-{index}",
            title=f"Track {index}",
            artist="Benchmark artist",
            duration=180,
            source="YouTube",
            webpage_url=f"https://example.invalid/{prefix}/{index}",
        )
        for index in range(count)
    ]


class _SearchRecorder:
    def __init__(self, app, query: str) -> None:
        self.app = app
        self.query = query
        self.started = 0.0
        self.first_paint_ms: float | None = None
        self.finished_ms: float | None = None
        self.partial_render_ms: dict[int, list[float]] = defaultdict(list)
        self.provider_statuses: dict[str, tuple[str, int, float | None]] = {}
        self._render = app.search_view.render_results
        self._status = app.search_view.set_provider_status
        self._finish = app._finish_search

    def install(self) -> None:
        def render(tracks, message=None):
            started = time.perf_counter()
            result = self._render(tracks, message)
            self.app.update_idletasks()
            elapsed = (time.perf_counter() - started) * 1000
            if tracks:
                self.partial_render_ms[len(tracks)].append(elapsed)
                if self.first_paint_ms is None:
                    self.first_paint_ms = (time.perf_counter() - self.started) * 1000
            return result

        def status(provider, state, count=0, duration=None):
            self.provider_statuses[provider] = (state, count, duration)
            return self._status(provider, state, count, duration)

        def finish(future, generation):
            result = self._finish(future, generation)
            self.finished_ms = (time.perf_counter() - self.started) * 1000
            return result

        self.app.search_view.render_results = render
        self.app.search_view.set_provider_status = status
        self.app._finish_search = finish

    def restore(self) -> None:
        self.app.search_view.render_results = self._render
        self.app.search_view.set_provider_status = self._status
        self.app._finish_search = self._finish


def _run_until(app, done: Callable[[], bool], timeout: float = 12.0) -> None:
    deadline = time.perf_counter() + timeout
    while not done():
        if time.perf_counter() >= deadline:
            raise TimeoutError(f"UI benchmark timed out after {timeout:.0f}s")
        app.update()
        time.sleep(0.001)


def _pump_list_renderer(app, view, timeout: float = 15.0) -> float:
    started = time.perf_counter()
    _run_until(app, lambda: view._renderer._after_id is None, timeout)
    return (time.perf_counter() - started) * 1000


def _install_baseline_list_replay(renderer) -> Callable[[], None]:
    """Replay the original synchronous full-destroy/full-create list update."""
    from mmp.ui.components.track_row import TrackRow

    old_render = renderer.render

    def destructive_render(items, empty_message, *, scroll_key="default"):
        for child in renderer.frame.winfo_children():
            child.destroy()
        renderer.rows = {}
        renderer._clear_empty()
        hooks = getattr(renderer.app, "_row_repaint_hooks_by_context", {}).get(renderer.context)
        if hooks is not None:
            hooks.clear()

        for index, item in enumerate(items):
            row = TrackRow.create(
                renderer.app,
                renderer.frame,
                item.track,
                context=renderer.context,
                index=index,
                trailing=item.trailing,
            )
            renderer.rows[item.key] = row
            if index == 0 and hasattr(renderer, "_mmp_measure_started"):
                renderer._mmp_first_created_ms = (time.perf_counter() - renderer._mmp_measure_started) * 1000

        renderer._target_keys = [item.key for item in items]
        renderer._target_indices = {item.key: index for index, item in enumerate(items)}
        renderer._current_order = list(renderer._target_keys)
        renderer._pending_items = []
        renderer._pending_index = 0
        renderer._stale_keys = []
        renderer._empty_message_pending = None
        renderer._active_scroll_key = scroll_key
        renderer._after_id = None
        if not items:
            renderer._show_empty(empty_message)
        renderer._set_loading(False)
        renderer.app.after_idle(renderer._restore_scroll_position)

    renderer.render = destructive_render

    def restore() -> None:
        renderer.render = old_render

    return restore


def _measure_list_reconcile(app, view, page: str) -> dict[str, float]:
    renderer = view._renderer
    if renderer._after_id is not None:
        _run_until(app, lambda: renderer._after_id is None)

    app.show_page("search")
    app.update_idletasks()
    started = time.perf_counter()
    renderer._mmp_measure_started = started
    renderer._mmp_first_created_ms = None
    original_process_batch = renderer._process_batch
    first_batch: list[float] = []

    def measured_process_batch(generation: int) -> None:
        original_process_batch(generation)
        if not first_batch and (renderer._pending_index > 0 or renderer._after_id is None):
            first_batch.append((time.perf_counter() - started) * 1000)

    renderer._process_batch = measured_process_batch
    try:
        app.show_page(page)
        app.update_idletasks()
        navigation_ms = (time.perf_counter() - started) * 1000

        if renderer._after_id is not None:
            _run_until(app, lambda: bool(first_batch) or renderer._after_id is None)
            first_batch_ms = first_batch[0] if first_batch else (time.perf_counter() - started) * 1000
            _run_until(app, lambda: renderer._after_id is None)
        else:
            first_batch_ms = renderer._mmp_first_created_ms or navigation_ms

        complete_ms = (time.perf_counter() - started) * 1000
    finally:
        renderer._process_batch = original_process_batch
        del renderer._mmp_measure_started
        del renderer._mmp_first_created_ms
    return {
        "navigation_return_ms": navigation_ms,
        "first_reconciled_batch_ms": first_batch_ms,
        "full_completion_ms": complete_ms,
    }


def _create_download_fixture(folder: Path, prefix: str, count: int) -> list[Path]:
    folder.mkdir(parents=True, exist_ok=True)
    paths = []
    for index in range(count):
        path = folder / f"{prefix}-{index:04}.mp3"
        path.write_bytes(b"benchmark")
        paths.append(path)
    return paths


def _benchmark_100_row_update(
    app,
    kind: str,
    operation: str,
    *,
    baseline: bool,
    temp_dir: Path,
    samples: int = 2,
) -> dict[str, dict]:
    """Measure a same-size 100-row replacement or one-item list mutation."""
    from mmp.queue_manager import PlaybackQueue

    if kind == "queue":
        view, page = app.queue_view, "upnext"
    elif kind == "library":
        view, page = app.library_view, "library"
    else:
        view, page = app.downloads_view, "downloads"

    renderer = view._renderer
    restore = _install_baseline_list_replay(renderer) if baseline else None
    metrics: dict[str, list[float]] = {
        "navigation_return_ms": [],
        "first_reconciled_batch_ms": [],
        "full_completion_ms": [],
    }
    prior_favorites = app.library.favorites
    try:
        for sample in range(samples):
            fixture_name = f"{kind}-{operation}-{sample}"
            old_tracks = _tracks(100, f"{fixture_name}-old")
            file_paths: list[Path] = []

            if kind == "queue":
                app.queue = PlaybackQueue()
                for track in old_tracks:
                    app.queue.add(track)
                view.invalidate()
            elif kind == "library":
                app.library.favorites = lambda rows=old_tracks: list(rows)
                view.library_segment.set("Favorites")
                view.invalidate()
            else:
                file_paths = _create_download_fixture(temp_dir / fixture_name, "old", 100)
                view._list_downloaded_files = lambda rows=file_paths: list(rows)
                view.invalidate()

            app.show_page(page)
            app.update_idletasks()
            if renderer._after_id is not None:
                _pump_list_renderer(app, view)

            app.show_page("search")
            app.update_idletasks()

            if operation == "single_add":
                if kind == "queue":
                    app.queue.add(_tracks(1, f"{fixture_name}-added")[0])
                    view.invalidate()
                elif kind == "library":
                    old_tracks.append(_tracks(1, f"{fixture_name}-added")[0])
                    view.invalidate()
                else:
                    added = _create_download_fixture(temp_dir / fixture_name / "added", "new", 1)[0]
                    file_paths.append(added)
                    view.invalidate()
            elif operation == "single_middle_remove":
                if kind == "queue":
                    app.queue.remove_at(50)
                    view.invalidate()
                elif kind == "library":
                    old_tracks.pop(50)
                    view.invalidate()
                else:
                    file_paths.pop(50).unlink()
                    view.invalidate()
            else:
                new_tracks = _tracks(100, f"{fixture_name}-new")
                if kind == "queue":
                    app.queue = PlaybackQueue()
                    for track in new_tracks:
                        app.queue.add(track)
                    view.invalidate()
                elif kind == "library":
                    app.library.favorites = lambda rows=new_tracks: list(rows)
                    view.invalidate()
                else:
                    file_paths = _create_download_fixture(temp_dir / fixture_name / "new", "new", 100)
                    view._list_downloaded_files = lambda rows=file_paths: list(rows)
                    view.invalidate()

            sample_metrics = _measure_list_reconcile(app, view, page)
            for key, value in sample_metrics.items():
                metrics[key].append(value)
    finally:
        if restore is not None:
            restore()
        app.library.favorites = prior_favorites

    return {key: _summary(values) for key, values in metrics.items()}


def _measure_cold_search(app, query: str, sample: int) -> _SearchRecorder:
    from mmp.models import Track

    delays = {"YouTube": 0.040, "YouTube Music": 0.250, "SoundCloud": 0.120}

    async def provider(_url: str, name: str) -> list[Track]:
        await asyncio.sleep(delays[name])
        return [_track(f"{sample}", name, index) for index in range(3)]

    app.search_service._search_source = provider
    app.search_view.search_controller.set_text(query)
    recorder = _SearchRecorder(app, query)
    recorder.install()
    recorder.started = time.perf_counter()
    app._start_search()
    _run_until(app, lambda: recorder.finished_ms is not None)
    recorder.restore()
    return recorder


def _measure_cached_search(app, query: str) -> _SearchRecorder:
    app.search_view.search_controller.set_text(query)
    recorder = _SearchRecorder(app, query)
    recorder.install()
    recorder.started = time.perf_counter()
    app._start_search()
    _run_until(app, lambda: recorder.finished_ms is not None)
    recorder.restore()
    return recorder


def _measure_search_render(app, count: int, sample: int) -> float:
    if count == 0:
        started = time.perf_counter()
        app.search_view.render_results([], message=f"Benchmark empty {sample}")
        app.update_idletasks()
        return (time.perf_counter() - started) * 1000
    rows = _tracks(count, f"search-render-{count}-{sample}")
    started = time.perf_counter()
    app.search_view.render_results(rows)
    app.update_idletasks()
    return (time.perf_counter() - started) * 1000


def _install_baseline_search_path(app) -> Callable[[], None]:
    """Replay the pre-change destroy-and-recreate search rendering path."""
    from mmp.ui.components.track_row import TrackRow

    view = app.search_view
    old_render = view.render_results
    old_queue = app._queue_search_partial_results

    def destructive_render(tracks, message=None):
        for child in view.results_frame.winfo_children():
            child.destroy()
        view._rows = {}
        view._empty_label = None
        view._empty_message = None
        hooks = app._row_repaint_hooks_by_context["search"]
        hooks.clear()
        app._row_repaint_hooks = []
        if message:
            view._empty_state(message)
            return
        if not tracks:
            view._empty_state("Search for a track to begin.\nResults appear here.")
            return
        for index, track in enumerate(tracks):
            TrackRow.create(app, view.results_frame, track, context="search", index=index)

    def direct_partial_paint(tracks, generation):
        app._show_partial_search_results(tracks, generation)

    view.render_results = destructive_render
    app._queue_search_partial_results = direct_partial_paint

    def restore() -> None:
        view.render_results = old_render
        app._queue_search_partial_results = old_queue
        for child in view.results_frame.winfo_children():
            child.destroy()
        view._rows = {}
        view._empty_label = None
        view._empty_message = None
        app._row_repaint_hooks_by_context["search"].clear()

    return restore


def _make_queue(app, count: int, prefix: str) -> None:
    from mmp.queue_manager import PlaybackQueue

    app.queue = PlaybackQueue()
    for track in _tracks(count, prefix):
        app.queue.add(track)
    app.queue_view.invalidate()


def run_benchmarks(*, sandbox_safe_loop: bool, include_live: bool) -> dict:
    if sandbox_safe_loop:
        _install_sandbox_safe_asyncio_loop()

    import mmp.app
    import mmp.config
    from mmp.models import Track

    temp_dir = Path(tempfile.mkdtemp(prefix=".mmp-perf-", dir=Path.cwd())).resolve()
    app = None
    try:
        mmp.app.APP_DIR = temp_dir
        mmp.config.APP_DIR = temp_dir
        mmp.app.AudioPlayer = MagicMock
        app = mmp.app.MagicMusicPlayerApp()
        app.withdraw()
        app.toast = lambda _message: None
        print("Native UI ready; running fixed-result search samples.", file=sys.stderr, flush=True)
        report: dict = {
            "runtime": "Python/Tk/CustomTkinter on this workstation",
            "network": "none for fixed-result cases",
            "sandbox_safe_loop": sandbox_safe_loop,
            "event_loop_measurement_note": (
                "10 ms proactor polling workaround enabled for this sandbox; scheduling p95 is coarse."
                if sandbox_safe_loop
                else "Native event loop used."
            ),
            "fixtures": {
                "search_samples": 5,
                "search_render_samples_per_size": 3,
                "clean_tab_switch_samples_per_size": 5,
                "dirty_queue_and_download_samples_per_size": 2,
                "list_sizes": [0, 30, 100],
                "stable_list_update_samples_per_scenario": 2,
                "stable_list_rows": 100,
                "single_remove_index": 50,
                "list_reconcile_batch_size": {
                    "first": app.queue_view._renderer.FIRST_BATCH_SIZE,
                    "subsequent": app.queue_view._renderer.BATCH_SIZE,
                },
                "provider_delays_ms": {"YouTube": 40, "SoundCloud": 120, "YouTube Music": 250},
            },
        }

        baseline_restore = _install_baseline_search_path(app)
        baseline_first_ms: list[float] = []
        baseline_full_ms: list[float] = []
        baseline_provider_ms: dict[str, list[float]] = defaultdict(list)
        baseline_partial_ms: dict[int, list[float]] = defaultdict(list)
        for sample in range(5):
            recorder = _measure_cold_search(app, f"baseline replay {sample}", sample)
            if recorder.first_paint_ms is not None:
                baseline_first_ms.append(recorder.first_paint_ms)
            if recorder.finished_ms is not None:
                baseline_full_ms.append(recorder.finished_ms)
            for count, values in recorder.partial_render_ms.items():
                baseline_partial_ms[count].extend(values)
            for provider, (_state, _count, duration) in recorder.provider_statuses.items():
                if duration is not None:
                    baseline_provider_ms[provider].append(duration * 1000)
            print(f"Completed baseline replay search {sample + 1}/5.", file=sys.stderr, flush=True)
        baseline_cache_paint_ms = [
            _measure_cached_search(app, "baseline replay 4").first_paint_ms or 0.0 for _ in range(5)
        ]
        baseline_restore()

        first_ms: list[float] = []
        full_ms: list[float] = []
        provider_ms: dict[str, list[float]] = defaultdict(list)
        partial_paint_ms: dict[int, list[float]] = defaultdict(list)
        for sample in range(5):
            recorder = _measure_cold_search(app, f"benchmark query {sample}", sample + 5)
            if recorder.first_paint_ms is not None:
                first_ms.append(recorder.first_paint_ms)
            if recorder.finished_ms is not None:
                full_ms.append(recorder.finished_ms)
            for count, values in recorder.partial_render_ms.items():
                partial_paint_ms[count].extend(values)
            for provider, (_state, _count, duration) in recorder.provider_statuses.items():
                if duration is not None:
                    provider_ms[provider].append(duration * 1000)
            print(f"Completed coalesced search {sample + 1}/5.", file=sys.stderr, flush=True)

        cache_lookup_ms = []
        cached_query = "benchmark query 4"
        for _ in range(5):
            started = time.perf_counter()
            app.search_service.get_cached_search(cached_query)
            cache_lookup_ms.append((time.perf_counter() - started) * 1000)
        cache_paint_ms = [
            _measure_cached_search(app, cached_query).first_paint_ms or 0.0 for _ in range(5)
        ]

        report["search"] = {
            "cold_time_to_first_painted_results": _summary(first_ms),
            "cold_time_to_full_results": _summary(full_ms),
            "provider_elapsed_ms": {name: _summary(values) for name, values in provider_ms.items()},
            "cache_lookup": _summary(cache_lookup_ms),
            "cached_results_to_first_paint_ms": _summary(cache_paint_ms),
            "partial_result_render_by_row_count": {
                str(count): _summary(values) for count, values in partial_paint_ms.items()
            },
        }

        report["baseline_path_replay_search"] = {
            "cold_time_to_first_painted_results": _summary(baseline_first_ms),
            "cold_time_to_full_results": _summary(baseline_full_ms),
            "provider_elapsed_ms": {name: _summary(values) for name, values in baseline_provider_ms.items()},
            "partial_result_render_by_row_count": {
                str(count): _summary(values) for count, values in baseline_partial_ms.items()
            },
            "cached_results_to_first_paint_ms": _summary(baseline_cache_paint_ms),
            "note": "Replays the original full-destroy render and immediate partial callback path in the same runtime.",
        }

        baseline_render_restore = _install_baseline_search_path(app)
        baseline_search_render: dict[str, dict] = {}
        for count in (0, 9, 60):
            values = [_measure_search_render(app, count, sample) for sample in range(3)]
            baseline_search_render[str(count)] = _summary(values)
        baseline_render_restore()

        search_render: dict[str, dict] = {}
        for count in (0, 9, 60):
            values = [_measure_search_render(app, count, sample) for sample in range(3)]
            search_render[str(count)] = _summary(values)
            print(f"Completed search render case ({count} rows).", file=sys.stderr, flush=True)
        report["cold_search_render_ms_by_rows"] = search_render
        report["baseline_search_render_ms_by_rows"] = baseline_search_render

        clean_switch: dict[str, dict] = {}
        dirty_queue_open: dict[str, dict] = {}
        dirty_queue_first_batch: dict[str, dict] = {}
        dirty_queue_complete: dict[str, dict] = {}
        for count in (0, 30, 100):
            _make_queue(app, count, f"queue-warm-{count}")
            app.show_page("upnext")
            app.update_idletasks()
            _pump_list_renderer(app, app.queue_view)
            values = []
            for _ in range(5):
                app.show_page("search")
                app.update_idletasks()
                started = time.perf_counter()
                app.show_page("upnext")
                app.update_idletasks()
                values.append((time.perf_counter() - started) * 1000)
            clean_switch[str(count)] = _summary(values)

            opened = []
            first_batch = []
            completed = []
            for sample in range(2):
                app.show_page("search")
                app.update_idletasks()
                _make_queue(app, count, f"queue-dirty-{count}-{sample}")
                measured = _measure_list_reconcile(app, app.queue_view, "upnext")
                opened.append(measured["navigation_return_ms"])
                first_batch.append(measured["first_reconciled_batch_ms"])
                completed.append(measured["full_completion_ms"])
            dirty_queue_open[str(count)] = _summary(opened)
            dirty_queue_first_batch[str(count)] = _summary(first_batch)
            dirty_queue_complete[str(count)] = _summary(completed)
            print(f"Completed queue list cases ({count} rows).", file=sys.stderr, flush=True)

        report["already_rendered_queue_tab_switch_ms"] = clean_switch
        report["dirty_queue_navigation_open_ms"] = dirty_queue_open
        report["dirty_queue_first_reconciled_batch_ms"] = dirty_queue_first_batch
        report["dirty_queue_render_complete_ms"] = dirty_queue_complete

        dirty_download_open: dict[str, dict] = {}
        dirty_download_first_batch: dict[str, dict] = {}
        dirty_download_complete: dict[str, dict] = {}
        for count in (0, 30, 100):
            opened = []
            first_batch = []
            completed = []
            for sample in range(2):
                folder = temp_dir / f"downloads-{count}-{sample}"
                folder.mkdir()
                paths = []
                for index in range(count):
                    path = folder / f"{sample}-{index:04}.mp3"
                    path.write_bytes(b"benchmark")
                    paths.append(path)
                app.downloads_view._list_downloaded_files = lambda snapshot=paths: snapshot
                app.downloads_view.invalidate()
                app.show_page("search")
                app.update_idletasks()
                measured = _measure_list_reconcile(app, app.downloads_view, "downloads")
                opened.append(measured["navigation_return_ms"])
                first_batch.append(measured["first_reconciled_batch_ms"])
                completed.append(measured["full_completion_ms"])
            dirty_download_open[str(count)] = _summary(opened)
            dirty_download_first_batch[str(count)] = _summary(first_batch)
            dirty_download_complete[str(count)] = _summary(completed)
            print(f"Completed downloads list cases ({count} rows).", file=sys.stderr, flush=True)

        report["dirty_download_navigation_open_ms"] = dirty_download_open
        report["dirty_download_first_reconciled_batch_ms"] = dirty_download_first_batch
        report["dirty_download_render_complete_ms"] = dirty_download_complete

        list_update_comparison: dict[str, dict] = {}
        for kind in ("queue", "library", "downloads"):
            cases: dict[str, dict] = {}
            for operation in ("all_new", "single_add", "single_middle_remove"):
                label = "all_new_100_rows" if operation == "all_new" else operation
                baseline_metrics = _benchmark_100_row_update(
                    app, kind, operation, baseline=True, temp_dir=temp_dir
                )
                row_cache_metrics = _benchmark_100_row_update(
                    app, kind, operation, baseline=False, temp_dir=temp_dir
                )
                cases[label] = {
                    "baseline_full_replacement": baseline_metrics,
                    "row_cache_reconciliation": row_cache_metrics,
                }
                print(f"Completed {kind} 100-row {operation} comparison.", file=sys.stderr, flush=True)
            list_update_comparison[kind] = cases
        report["100_row_list_update_comparison"] = list_update_comparison
        report["list_timing_note"] = (
            "Navigation return includes synchronous snapshot/status work. First reconciled batch means the first "
            "new, removed, or reindexed rows were handled. Completion waits for every required row update and stale-row removal. "
            "The baseline replays synchronous full destruction and recreation in the same process."
        )

        lyric_repeat = []
        for _ in range(4):
            app.show_page("search")
            app.update_idletasks()
            started = time.perf_counter()
            app.show_page("lyrics")
            app.update_idletasks()
            lyric_repeat.append((time.perf_counter() - started) * 1000)
        report["repeat_no_track_lyrics_tab_switch_ms"] = _summary(lyric_repeat)

        if include_live:
            app.search_service._search_source = mmp.app.SearchService._search_source.__get__(
                app.search_service, type(app.search_service)
            )
            app.search_view.search_controller.set_text("Radiohead Creep")
            live = _SearchRecorder(app, "Radiohead Creep")
            live.install()
            live.started = time.perf_counter()
            app._start_search()
            try:
                _run_until(app, lambda: live.finished_ms is not None, timeout=20.0)
                report["single_live_search"] = {
                    "elapsed_to_first_paint_ms": live.first_paint_ms,
                    "elapsed_to_full_results_ms": live.finished_ms,
                    "provider_state_and_elapsed_ms": {
                        name: {"state": state, "duration_ms": round(duration * 1000, 2) if duration is not None else None}
                        for name, (state, _count, duration) in live.provider_statuses.items()
                    },
                }
            except TimeoutError as error:
                report["single_live_search"] = {"error": str(error), "provider_state_and_elapsed_ms": live.provider_statuses}
            finally:
                live.restore()

        return report
    finally:
        if app is not None:
            try:
                app.worker.stop()
                app.library.close()
                app.destroy()
            except Exception:
                pass
        shutil.rmtree(temp_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sandbox-safe-loop",
        action="store_true",
        help="Sandbox-only workaround for a Windows runtime that blocks localhost socketpair; adds up to 10 ms polling granularity.",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="Run one real search after the fixed-result benchmark; this contacts providers once.",
    )
    args = parser.parse_args()
    print(json.dumps(run_benchmarks(sandbox_safe_loop=args.sandbox_safe_loop, include_live=args.live), indent=2))


if __name__ == "__main__":
    main()
