from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from mmp.app import MagicMusicPlayerApp
from mmp.lyrics import LyricsData, LyricsService
from mmp.models import Track
from mmp.search import ProviderSearchStatus, SearchService
from mmp.ui.components.track_row import TrackRow
from mmp.ui.views.downloads_view import DownloadsView
from mmp.ui.views.list_renderer import RenderedTrack, TrackListRenderer
from mmp.ui.views.lyrics_view import LyricsView
from mmp.ui.views.search_view import SearchView


def _track(track_id: str, url: str | None = None, source: str = "YouTube") -> Track:
    return Track(
        id=track_id,
        title=f"Track {track_id}",
        artist="Test Artist",
        duration=180,
        source=source,
        webpage_url=url or f"https://example.test/{track_id}",
    )


def _run(coro):
    return asyncio.run(coro)


def test_search_provider_completion_failure_dedup_and_cache() -> None:
    service = SearchService(limit_per_source=3)
    completion: list[ProviderSearchStatus] = []
    partial: list[list[Track]] = []
    started: list[str] = []

    async def fake_search(url: str, provider: str) -> list[Track]:
        started.append(provider)
        if provider == "SoundCloud":
            await asyncio.sleep(0.025)
            raise RuntimeError("offline")
        await asyncio.sleep(0.05 if provider == "YouTube" else 0.09)
        common = _track(f"{provider}-common", "https://example.test/shared", provider)
        own = _track(f"{provider}-own", f"https://example.test/{provider}", provider)
        return [common, own]

    service._search_source = fake_search  # type: ignore[method-assign]
    result = _run(
        service.search(
            "provider order",
            refresh=True,
            on_partial=lambda rows: partial.append(list(rows)),
            on_provider_status=completion.append,
        )
    )

    assert set(started) == {"YouTube", "YouTube Music", "SoundCloud"}
    assert [status.provider for status in completion] == ["SoundCloud", "YouTube", "YouTube Music"]
    assert [status.state for status in completion] == ["failed", "done", "done"]
    assert all(status.duration_seconds > 0 for status in completion)
    assert len(partial) == 2
    assert [track.webpage_url for track in result] == [
        "https://example.test/shared",
        "https://example.test/YouTube",
        "https://example.test/YouTube Music",
    ]

    cached = _run(service.search("  PROVIDER   ORDER "))
    assert cached == result
    assert len(started) == 3


class _FakeCanvas:
    def __init__(self, position: float = 0.0) -> None:
        self.position = position

    def yview(self):
        return self.position, min(1.0, self.position + 0.2)

    def yview_moveto(self, position: float) -> None:
        self.position = position


class _FakeFrame:
    def __init__(self, position: float = 0.0) -> None:
        self.children = []
        self._parent_canvas = _FakeCanvas(position)

    def grid_columnconfigure(self, *_args, **_kwargs) -> None:
        pass

    def winfo_children(self):
        return list(self.children)


class _FakeLabel:
    created = 0

    def __init__(self, parent, **kwargs) -> None:
        type(self).created += 1
        self.parent = parent
        self.options = dict(kwargs)
        self.destroyed = False
        parent.children.append(self)

    def pack(self, **_kwargs) -> None:
        pass

    def grid(self, **_kwargs) -> None:
        pass

    def configure(self, **kwargs) -> None:
        self.options.update(kwargs)

    def cget(self, name):
        return self.options.get(name)

    def destroy(self) -> None:
        self.destroyed = True
        if self in self.parent.children:
            self.parent.children.remove(self)


class _FakeRow:
    def __init__(self, parent, track: Track, index: int, context: str, trailing=None) -> None:
        self.parent = parent
        self.track = track
        self.index = index
        self.context = context
        self.trailing = trailing
        self.destroyed = False
        self.hidden = False
        self.repaint_calls = 0
        self.update_calls = 0
        self._mmp_track_id = track.id
        self._mmp_state = {"track": track, "trailing": trailing, "index": index}
        self._mmp_repaint = self.repaint
        self._mmp_repaint_entry = (track.id, self.repaint)
        self._mmp_update = self.update
        parent.children.append(self)

    def update(self, track, index, trailing=None) -> None:
        self.update_calls += 1
        self.track, self.index, self.trailing = track, index, trailing
        self._mmp_state.update(track=track, trailing=trailing, index=index)
        self.hidden = False

    def repaint(self) -> None:
        self.repaint_calls += 1

    def grid_remove(self) -> None:
        self.hidden = True

    def grid(self, **kwargs) -> None:
        self.index = kwargs.get("row", self.index)
        self.hidden = False

    def destroy(self) -> None:
        self.destroyed = True
        if self in self.parent.children:
            self.parent.children.remove(self)


class _FakeApp:
    def __init__(self) -> None:
        self.palette = SimpleNamespace(muted="#777")
        self._row_repaint_hooks_by_context = {"search": [], "queue": [], "library": [], "downloads": []}
        self._jobs: dict[str, object] = {}
        self._next_job = 0

    def _themed(self, widget, **_kwargs):
        return widget

    def after(self, _delay, callback):
        self._next_job += 1
        job_id = str(self._next_job)
        self._jobs[job_id] = callback
        return job_id

    def after_cancel(self, job_id) -> None:
        self._jobs.pop(job_id, None)

    def after_idle(self, callback) -> None:
        callback()

    def run_pending(self) -> None:
        while self._jobs:
            _job_id, callback = self._jobs.popitem()
            callback()


def test_search_view_reuses_rows_across_partial_snapshots(monkeypatch) -> None:
    app = _FakeApp()
    frame = _FakeFrame()
    view = SearchView.__new__(SearchView)
    view.app = app
    view.results_frame = frame
    view._rows = {}
    view._empty_label = None
    view._empty_message = None
    created: list[_FakeRow] = []
    updated: list[tuple[str, int]] = []

    def create(_app, parent, track, context, index=0, trailing=None):
        row = _FakeRow(parent, track, index, context, trailing)
        created.append(row)
        return row

    def update(_app, row, track, _context, index, _trailing=None):
        row.update(track, index)
        updated.append((track.id, index))

    monkeypatch.setattr(TrackRow, "create", create)
    monkeypatch.setattr(TrackRow, "update", update)
    first = _track("one")
    second = _track("two")
    view.render_results([first])
    first_row = view._rows[first.webpage_url]
    view.render_results([first, second])

    assert len(created) == 2
    assert view._rows[first.webpage_url] is first_row
    assert updated == [("one", 0)]
    view.render_results([second])
    assert view._rows[second.webpage_url] is created[1]
    assert first_row.destroyed


def test_queued_partials_coalesce_and_stale_searches_are_ignored() -> None:
    callbacks: list[object] = []
    rendered: list[list[Track]] = []
    app = SimpleNamespace(
        _search_generation=4,
        _search_using_cache_generation=None,
        _search_partial_snapshot=None,
        _search_partial_after_id=None,
        after=lambda _delay, callback: callbacks.append(callback) or "after-1",
        after_idle=lambda callback: callbacks.append(callback) or "idle-1",
        _flush_search_partial_results=None,
        _show_partial_search_results=None,
        active_page="search",
        last_results=[],
        _search_results_pending=True,
        _search_results_dirty=False,
        search_view=SimpleNamespace(render_results=lambda rows: rendered.append(rows)),
        search_button=SimpleNamespace(configure=lambda **_kwargs: None),
    )
    app._flush_search_partial_results = lambda generation: MagicMusicPlayerApp._flush_search_partial_results(
        app, generation
    )
    app._show_partial_search_results = lambda rows, generation: MagicMusicPlayerApp._show_partial_search_results(
        app, rows, generation
    )
    one, two = _track("one"), _track("two")
    MagicMusicPlayerApp._queue_search_partial_results(app, [one], 4)
    MagicMusicPlayerApp._queue_search_partial_results(app, [one, two], 4)
    assert len(callbacks) == 1
    assert app._search_partial_snapshot == ([one, two], 4)
    callbacks[0]()
    assert app.last_results == [one, two]
    assert rendered == [[one, two]]

    before = list(app.last_results)
    MagicMusicPlayerApp._show_partial_search_results(app, [_track("stale")], 3)
    assert app.last_results == before
    assert rendered == [[one, two]]


def test_large_list_renderer_batches_rows_and_restores_scroll(monkeypatch) -> None:
    from mmp.ui.views import list_renderer

    app = _FakeApp()
    frame = _FakeFrame(position=0.37)
    created: list[_FakeRow] = []

    def create(_app, parent, track, context, index=0, trailing=None):
        row = _FakeRow(parent, track, index, context, trailing)
        created.append(row)
        return row

    monkeypatch.setattr(TrackRow, "create", create)
    monkeypatch.setattr(list_renderer.ctk, "CTkLabel", _FakeLabel)
    monkeypatch.setattr(list_renderer.ctk, "CTkFont", lambda **_kwargs: None)
    renderer = TrackListRenderer(app, frame, "queue")
    items = [RenderedTrack(track.id, track) for track in (_track(str(index)) for index in range(100))]

    renderer.render(items, "empty")
    assert len(created) == 0
    assert app._jobs
    _first_job, first_callback = app._jobs.popitem()
    first_callback()
    assert len(created) == renderer.FIRST_BATCH_SIZE
    app.run_pending()
    assert len(created) == 100
    assert frame._parent_canvas.position == 0.37

    renderer.render(items, "empty")
    assert len(created) == 100
    assert not app._jobs
    assert len(renderer.rows) == 100

    added = RenderedTrack("added", _track("added"))
    renderer.render([*items, added], "empty")
    assert len(created) == 100
    app.run_pending()
    assert len(created) == 101
    assert sum(row.update_calls for row in renderer.rows.values()) == 0

    remove_index = 50
    after_removal = [*items[:remove_index], *items[remove_index + 1 :], added]
    renderer.render(after_removal, "empty")
    app.run_pending()
    assert len(created) == 101
    assert items[remove_index].key not in renderer.rows
    assert sum(row.update_calls for row in renderer.rows.values()) == 50


def test_repeated_empty_list_and_tab_switch_do_not_rebuild_or_repaint(monkeypatch) -> None:
    from mmp.ui.views import list_renderer

    app = _FakeApp()
    frame = _FakeFrame()
    monkeypatch.setattr(list_renderer.ctk, "CTkLabel", _FakeLabel)
    monkeypatch.setattr(list_renderer.ctk, "CTkFont", lambda **_kwargs: None)
    _FakeLabel.created = 0
    renderer = TrackListRenderer(app, frame, "queue")
    renderer.render([], "Queue is empty")
    first_label = renderer._empty_label
    renderer.render([], "Queue is empty")
    assert renderer._empty_label is first_label
    assert _FakeLabel.created == 1

    raised: list[str] = []
    app = SimpleNamespace(
        pages={"library": SimpleNamespace(tkraise=lambda: raised.append("library"))},
        active_page="search",
        _refresh_nav_active=lambda: None,
        library_view=SimpleNamespace(render_if_dirty=lambda: None),
        _repaint_rows=MagicMock(),
    )
    for _ in range(4):
        MagicMusicPlayerApp.show_page(app, "library")
    assert raised == ["library"] * 4
    app._repaint_rows.assert_not_called()


def test_favorite_repaint_only_touches_matching_rows() -> None:
    calls: list[str] = []
    app = SimpleNamespace(
        _row_repaint_hooks_by_context={
            "search": [("one", lambda: calls.append("search-one")), ("two", lambda: calls.append("search-two"))],
            "library": [("one", lambda: calls.append("library-one"))],
        }
    )
    MagicMusicPlayerApp._repaint_rows(app, {"one"})
    assert calls == ["search-one", "library-one"]


def test_download_render_reads_each_file_stat_once(monkeypatch, tmp_path: Path) -> None:
    files = [tmp_path / "one.mp3", tmp_path / "two.flac"]
    for index, path in enumerate(files):
        path.write_bytes(bytes(index + 1))
    reads: Counter[Path] = Counter()
    original_stat = Path.stat

    def counted_stat(path, *args, **kwargs):
        if path in files:
            reads[path] += 1
        return original_stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", counted_stat)
    view = DownloadsView.__new__(DownloadsView)
    view._dirty = True
    view._list_downloaded_files = lambda: files
    view.downloads_count_label = SimpleNamespace(configure=lambda **_kwargs: None)
    view._renderer = SimpleNamespace(render=lambda items, _empty: setattr(view, "items", items))
    view.app = SimpleNamespace()
    view.render()

    assert reads == Counter({files[0]: 1, files[1]: 1})
    assert len(view.items) == 2


def test_lyrics_view_deduplicates_pending_lookup_and_reuses_empty_state(monkeypatch) -> None:
    from mmp.ui.views import lyrics_view

    track = _track("lyrics")
    submitted = []

    async def lyrics_request(_track):
        return LyricsData(synced=[], plain=None)

    class Worker:
        def submit(self, coro, _callback=None):
            submitted.append(coro)
            coro.close()

    view = LyricsView.__new__(LyricsView)
    view.app = SimpleNamespace(
        current_track=track,
        worker=Worker(),
        lyrics_service=SimpleNamespace(get_lyrics=lyrics_request),
        palette=SimpleNamespace(muted="#777"),
    )
    view.track_info_label = SimpleNamespace(configure=lambda **_kwargs: None)
    view.current_track_id = None
    view.current_lyrics = None
    view.line_widgets = []
    view.active_line_index = -1
    view._loading_track_id = None
    view._view_state = None
    view._empty_message = None
    view._show_loading = lambda: None
    view.render()
    view.render()
    assert len(submitted) == 1

    frame = _FakeFrame()
    view.lyrics_frame = frame
    monkeypatch.setattr(lyrics_view.ctk, "CTkLabel", _FakeLabel)
    monkeypatch.setattr(lyrics_view.ctk, "CTkFont", lambda **_kwargs: None)
    _FakeLabel.created = 0
    view._view_state = None
    view._empty_message = None
    view._show_empty("No synchronized lyrics found for this track.")
    label = frame.children[0]
    view._show_empty("No synchronized lyrics found for this track.")
    assert frame.children == [label]
    assert _FakeLabel.created == 1


def test_lyrics_service_shares_inflight_lookup() -> None:
    service = LyricsService()
    track = _track("shared-lyrics")
    fetched: list[str] = []

    def fetch(_track):
        fetched.append(_track.id)
        return LyricsData(synced=[], plain="Lyrics")

    service._fetch_sync = fetch  # type: ignore[method-assign]

    async def concurrent_requests():
        return await asyncio.gather(service.get_lyrics(track), service.get_lyrics(track))

    first, second = _run(concurrent_requests())
    assert first == second == LyricsData(synced=[], plain="Lyrics")
    assert fetched == [track.id]
    assert track.id not in service._inflight

