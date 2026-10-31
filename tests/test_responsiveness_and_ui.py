from __future__ import annotations

import pathlib
import tempfile
from collections import OrderedDict
from types import SimpleNamespace
from unittest.mock import MagicMock

from PIL import Image

from mmp.app import MagicMusicPlayerApp
from mmp.models import Track
from mmp.thumbnails import ThumbnailService
from mmp.ui.components.track_row import TrackRow
from mmp.ui.views.downloads_view import DownloadsView
from mmp.ui.views.queue_view import QueueView
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


def test_cached_art_is_delivered_to_label(tmp_path: pathlib.Path, monkeypatch) -> None:
    """Verify bug fix: previously, cached_png hits resulted in empty art labels."""
    fake_png = tmp_path / "art.png"
    Image.new("RGB", (64, 64), color="blue").save(fake_png)

    app = SimpleNamespace(
        thumbnails=SimpleNamespace(
            cache_key=lambda _t: "test_key",
            cached_png=lambda _t: fake_png,
            get_cached_pil=lambda _k: Image.open(fake_png),
            load_async=MagicMock(),
        ),
        _art_labels={},
        _art_cache={},
        after=lambda _delay, fn: fn(),
        _deliver_art=lambda key, path: MagicMusicPlayerApp._deliver_art(app, key, path),
    )

    configured_options = {}

    class FakeLabel:
        def winfo_exists(self) -> bool:
            return True

        def configure(self, **kwargs) -> None:
            configured_options.update(kwargs)

    label = FakeLabel()
    track = _track("t1", url="http://test", source="YouTube")
    track = Track(
        id="t1",
        title="Title",
        artist="Artist",
        duration=120,
        source="YouTube",
        webpage_url="http://test",
        thumbnail_url="http://test.jpg",
    )

    MagicMusicPlayerApp._request_art(app, track, label, 48)

    assert "image" in configured_options
    assert configured_options["image"] is not None
    assert configured_options.get("text") == ""


def test_thumbnail_service_lru_eviction(tmp_path: pathlib.Path) -> None:
    """Verify memory cache does not grow unbounded."""
    service = ThumbnailService(tmp_path / "thumbs")
    service._max_memory = 3

    for index in range(5):
        img = Image.new("RGB", (10, 10))
        service._remember_pil(f"key_{index}", img)

    assert len(service._memory) == 3
    assert "key_0" not in service._memory
    assert "key_1" not in service._memory
    assert "key_4" in service._memory


def test_search_view_row_recycling() -> None:
    """Verify smart row recycling avoids widget destroy/create churn."""
    created: list[object] = []
    updated: list[tuple[str, int]] = []
    destroyed: list[object] = []

    class FakeRow:
        def __init__(self, track: Track, index: int) -> None:
            self.track = track
            self.index = index
            self._mmp_repaint_entry = (track.id, lambda: None)
            created.append(self)

        def destroy(self) -> None:
            destroyed.append(self)

    def fake_create(_app, _parent, track, context="search", index=0):
        return FakeRow(track, index)

    def fake_update(_app, row, track, context="search", index=0):
        updated.append((track.id, index))
        row.track = track
        row.index = index

    app = SimpleNamespace(
        palette=SimpleNamespace(muted="#777"),
        _row_repaint_hooks_by_context={"search": []},
    )
    view = SearchView.__new__(SearchView)
    view.app = app
    view.results_frame = SimpleNamespace()
    view._rows = {}
    view._empty_label = None
    view._empty_message = None

    import mmp.ui.views.search_view as sv_module
    orig_create = sv_module.TrackRow.create
    orig_update = sv_module.TrackRow.update
    sv_module.TrackRow.create = fake_create
    sv_module.TrackRow.update = fake_update

    try:
        # First search: 3 tracks
        t1, t2, t3 = _track("1"), _track("2"), _track("3")
        view.render_results([t1, t2, t3])
        assert len(created) == 3
        assert len(destroyed) == 0

        # Second search: 3 completely different tracks
        t4, t5, t6 = _track("4"), _track("5"), _track("6")
        view.render_results([t4, t5, t6])
        # Smart recycling must reuse the 3 existing rows instead of destroying and re-creating
        assert len(created) == 3, "New rows were created instead of recycled!"
        assert len(destroyed) == 0, "Existing rows were destroyed instead of recycled!"
        assert len(updated) == 3
        assert {t[0] for t in updated} == {"4", "5", "6"}

        # Third search: fewer tracks (2 tracks)
        t7, t8 = _track("7"), _track("8")
        view.render_results([t7, t8])
        # 2 rows recycled, 1 excess row destroyed
        assert len(created) == 3
        assert len(destroyed) == 1
    finally:
        sv_module.TrackRow.create = orig_create
        sv_module.TrackRow.update = orig_update


def test_views_have_count_text_on_init() -> None:
    """Verify DownloadsView and QueueView have _count_text to avoid AttributeError."""
    d_view = DownloadsView.__new__(DownloadsView)
    d_view._count_text = ""
    assert hasattr(d_view, "_count_text")

    q_view = QueueView.__new__(QueueView)
    q_view._count_text = ""
    assert hasattr(q_view, "_count_text")


def test_clear_search_cancels_inflight_search() -> None:
    """Verify clicking clear (X) in search view cancels any running search future."""
    fake_future = MagicMock()
    fake_future.done.return_value = False

    app = SimpleNamespace(
        search_future=fake_future,
        _cancel_pending_search_partial=MagicMock(),
    )
    view = SearchView.__new__(SearchView)
    view.app = app
    view.search_controller = MagicMock()
    view.search_entry = MagicMock()
    view.search_button = MagicMock()
    view.reset_provider_status = MagicMock()

    view._on_clear_search()

    fake_future.cancel.assert_called_once()
    app._cancel_pending_search_partial.assert_called_once()
    view.reset_provider_status.assert_called_once()
    view.search_button.configure.assert_called_with(state="normal", text="Search")
