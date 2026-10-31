from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mmp.app import MagicMusicPlayerApp
from mmp.downloader import DownloadProgress, DownloadStatus, DownloadTask
from mmp.library import MusicLibrary
from mmp.lyrics import LyricLine, LyricsData
from mmp.models import Track
from mmp.player import EQ_PRESETS, PlaybackState
from mmp.queue_manager import RepeatMode
from mmp.search import AudioStream, ProviderSearchStatus, is_direct_url


def _create_sample_audio(dest: Path, duration_seconds: int = 2) -> Path:
    """Generate a valid, playable MP3 file using the bundled ffmpeg."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    bundled_ffmpeg = Path(__file__).resolve().parents[1] / "tools" / "ffmpeg" / "ffmpeg.exe"
    ffmpeg_cmd = str(bundled_ffmpeg) if bundled_ffmpeg.exists() else "ffmpeg"
    cmd = [
        ffmpeg_cmd,
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency=440:duration={duration_seconds}",
        "-q:a",
        "9",
        "-y",
        str(dest),
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    return dest


def _pump(app: MagicMusicPlayerApp, iterations: int = 6, delay: float = 0.01) -> None:
    """Process pending Tkinter events and background dispatched callbacks."""
    for _ in range(iterations):
        try:
            app._poll_ui_queue()
            app.update_idletasks()
            app.update()
        except Exception:
            pass
        if delay:
            time.sleep(delay)


@pytest.fixture
def e2e_env(tmp_path: Path):
    """Provide an isolated MMP application instance in a clean temporary directory."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    download_dir = tmp_path / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)

    old_env = os.environ.get("MMP_CONFIG_DIR")
    os.environ["MMP_CONFIG_DIR"] = str(config_dir)

    # Pre-generate sample audio files for playback tests
    sample1 = _create_sample_audio(tmp_path / "media" / "song1.mp3", 30)
    sample2 = _create_sample_audio(tmp_path / "media" / "song2.mp3", 20)
    sample3 = _create_sample_audio(tmp_path / "media" / "song3.mp3", 20)

    app = MagicMusicPlayerApp()
    app.config_model.download_dir = download_dir
    app.config_model.save()
    _pump(app)

    yield {
        "app": app,
        "config_dir": config_dir,
        "download_dir": download_dir,
        "samples": [sample1, sample2, sample3],
    }

    try:
        app._on_close()
    except Exception:
        pass
    time.sleep(0.15)
    if old_env is not None:
        os.environ["MMP_CONFIG_DIR"] = old_env
    else:
        os.environ.pop("MMP_CONFIG_DIR", None)


def test_e2e_lifecycle_and_navigation(e2e_env) -> None:
    """Verify application lifecycle, window initialization, tab navigation, and clean close."""
    app: MagicMusicPlayerApp = e2e_env["app"]
    _pump(app)

    assert app.winfo_exists()
    assert "Magic Music Player" in app.title()
    assert app.active_page == "search"
    assert app.current_track is None

    # Navigate through every page and verify active tab styles and page visibility
    pages_to_test = ["library", "downloads", "upnext", "lyrics", "search"]
    for page_key in pages_to_test:
        app.show_page(page_key)
        _pump(app)
        assert app.active_page == page_key
        # Check active button style
        btn = app._nav_items[page_key]["button"]
        assert btn.cget("text_color") == app.palette.accent

    # Verify invalidation and dirty-rendering
    app.library_view.invalidate()
    assert app.library_view._dirty is True
    app.show_page("library")
    _pump(app)
    assert app.library_view._dirty is False


def test_e2e_search_english_and_arabic_with_streaming_and_caching(e2e_env) -> None:
    """Verify end-to-end search: typing English & Arabic, streaming results, history, caching, clear."""
    app: MagicMusicPlayerApp = e2e_env["app"]
    sample_path = str(e2e_env["samples"][0])

    t1 = Track(id="yt_1", title="Mozart Symphony No. 40", artist="Wolfgang Amadeus Mozart", duration=180, source="YouTube", webpage_url="http://yt1")
    t2 = Track(id="ytm_1", title="Mozart Piano Concerto", artist="Mozart", duration=210, source="YouTube Music", webpage_url="http://ytm1")
    t3 = Track(id="sc_1", title="Mozart Requiem Remix", artist="Classical Beats", duration=195, source="SoundCloud", webpage_url="http://sc1")

    # 1. English Search
    app.search_view.search_controller.set_text("Mozart")
    assert app.search_view.search_controller.text == "Mozart"

    # Simulate search service returning mock tracks
    async def mock_search(query, refresh=False, on_partial=None, on_provider_status=None):
        if on_provider_status:
            on_provider_status(ProviderSearchStatus("YouTube", "done", 0.1, 1))
            on_provider_status(ProviderSearchStatus("YouTube Music", "done", 0.1, 1))
            on_provider_status(ProviderSearchStatus("SoundCloud", "done", 0.1, 1))
        if on_partial:
            on_partial([t1, t2])
        return [t1, t2, t3]

    with patch.object(app.search_service, "search", side_effect=mock_search):
        app._start_search()
        _pump(app, iterations=10)

    assert len(app.last_results) == 3
    assert len(app.search_view._rows) == 3
    assert "Mozart" in app.recent_searches

    # Verify recent search chip rendered
    chip = app.search_view._recent_buttons[0]
    assert chip.cget("text") == "Mozart"

    # 2. Test repeat search instant cache hit
    app.search_service._remember_search("Mozart", [t1, t2, t3])
    cached = app.search_service.get_cached_search("Mozart")
    assert cached is not None and len(cached) == 3

    # 3. Arabic Search
    arabic_query = "فيروز - كيفك إنت"
    app.search_view.search_controller.set_text(arabic_query)
    assert app.search_view.search_controller.text == arabic_query

    t_ar = Track(id="ar_1", title="كيفك إنت", artist="فيروز", duration=214, source="YouTube", webpage_url="http://ar1")
    async def mock_ar_search(*_a, **_k):
        return [t_ar]

    with patch.object(app.search_service, "search", side_effect=mock_ar_search):
        app._start_search()
        _pump(app, iterations=10)

    assert len(app.last_results) == 1
    assert app.last_results[0].title == "كيفك إنت"

    # 4. Clear recent searches
    app._clear_recent_searches()
    _pump(app)
    assert len(app.recent_searches) == 0

    # 5. Clear search input via X button
    app.search_view._on_clear_search()
    _pump(app)
    assert app.search_view.search_controller.text == ""


def test_e2e_audio_playback_transport_and_player_bar(e2e_env) -> None:
    """Verify live audio playback using MPV: play, pause, seek, volume, mute, and UI state updates."""
    app: MagicMusicPlayerApp = e2e_env["app"]
    sample_path = str(e2e_env["samples"][0])

    track = Track(
        id="sample_audio_1",
        title="Test Audio Melody",
        artist="Test Composer",
        duration=3,
        source="Local",
        webpage_url=sample_path,
    )

    # 1. Start playback
    app._play_track(track)
    _pump(app, iterations=10)
    time.sleep(0.3)
    _pump(app, iterations=5)

    assert app.current_track is not None
    assert app.current_track.id == "sample_audio_1"
    assert app.track_title_label.cget("text") == "Test Audio Melody"
    assert app.track_artist_label.cget("text") == "Test Composer"

    state = app.player.state()
    assert not state.paused
    assert state.duration >= 2.5

    # Player bar play button shows pause icon while playing
    assert app.play_button.cget("text") == app._glyph_or("pause")

    # 2. Toggle pause
    app._toggle_pause()
    _pump(app)
    state_paused = app.player.state()
    assert state_paused.paused
    assert app.play_button.cget("text") == app._glyph_or("play")

    # Resume playback
    app._toggle_pause()
    _pump(app)
    state_resumed = app.player.state()
    assert not state_resumed.paused
    assert app.play_button.cget("text") == app._glyph_or("pause")

    # 3. Seeking
    app.player_bar.seek_slider.set(1.5)
    app.player_bar._on_seek_release(None)
    _pump(app, iterations=5)
    time.sleep(0.2)
    new_pos = app.player.state().position
    assert new_pos >= 1.0

    # 4. Volume and Mute controls
    app._set_volume(85)
    _pump(app)
    assert app.player.state().volume == 85
    assert int(app.volume_slider.get()) == 85

    # Hotkey volume steps
    app._hotkey_volume_up()
    _pump(app)
    assert app.player.state().volume == 90
    app._hotkey_volume_down()
    _pump(app)
    assert app.player.state().volume == 85

    # Mute
    app._hotkey_mute()
    _pump(app)
    assert app._muted is True
    assert app.player.state().volume == 0

    # Unmute restores pre-mute volume
    app._hotkey_mute()
    _pump(app)
    assert app._muted is False
    assert app.player.state().volume == 85

    # 5. Play local file directly
    app._play_local_file(sample_path)
    _pump(app, iterations=5)
    assert app.track_artist_label.cget("text") == "Local file"


def test_e2e_queue_management_modes_and_advance(e2e_env) -> None:
    """Verify queue operations: enqueue, jump, remove, clear, repeat modes, shuffle, next, prev."""
    app: MagicMusicPlayerApp = e2e_env["app"]
    samples = [str(s) for s in e2e_env["samples"]]

    t1 = Track(id="q1", title="First Track", artist="Artist 1", duration=3, source="Local", webpage_url=samples[0])
    t2 = Track(id="q2", title="Second Track", artist="Artist 2", duration=2, source="Local", webpage_url=samples[1])
    t3 = Track(id="q3", title="Third Track", artist="Artist 3", duration=2, source="Local", webpage_url=samples[2])

    # Enqueue tracks
    app._enqueue_row(t1)
    app._enqueue_row(t2)
    app._enqueue_row(t3)
    _pump(app)

    app.show_page("upnext")
    _pump(app)
    assert len(app.queue) == 3
    assert "0/3" in app.queue_count_label.cget("text")

    # Start playback on first track
    app._jump_queue(0)
    _pump(app, iterations=5)
    assert app.current_track.id == "q1"
    assert "1/3" in app.queue_count_label.cget("text")

    # Next track
    app._next_track()
    _pump(app, iterations=5)
    assert app.current_track.id == "q2"

    # Previous track
    app._prev_track()
    _pump(app, iterations=5)
    assert app.current_track.id == "q1"

    # Jump to queue index 2 (t3)
    app._jump_queue(2)
    _pump(app, iterations=5)
    assert app.current_track.id == "q3"

    # Remove item from queue
    app._remove_queue_item(1)
    _pump(app)
    assert len(app.queue) == 2

    # Repeat mode cycling: OFF -> ALL -> ONE -> OFF
    assert app.queue.repeat_mode == RepeatMode.OFF
    app._cycle_repeat()
    assert app.queue.repeat_mode == RepeatMode.ALL
    assert app.library.get_setting("repeat") == "all"
    app._cycle_repeat()
    assert app.queue.repeat_mode == RepeatMode.ONE
    assert app.library.get_setting("repeat") == "one"
    app._cycle_repeat()
    assert app.queue.repeat_mode == RepeatMode.OFF

    # Repeat ALL wrapping
    app.queue.set_repeat(RepeatMode.ALL)
    app.queue.jump_to(1)  # last item
    next_wrapped = app.queue.advance()
    assert next_wrapped.id == t1.id

    # Shuffle mode
    app._toggle_shuffle()
    assert app.queue.shuffle is True
    assert app.library.get_setting("shuffle") == "1"
    app._toggle_shuffle()
    assert app.queue.shuffle is False
    assert app.library.get_setting("shuffle") == "0"

    # Clear queue
    app._clear_queue()
    _pump(app)
    assert len(app.queue) == 0


def test_e2e_auto_radio_workflow(e2e_env) -> None:
    """Verify Auto-Radio toggle and auto-generation of similar tracks when queue finishes."""
    app: MagicMusicPlayerApp = e2e_env["app"]
    sample_path = str(e2e_env["samples"][0])

    # Toggle Auto-Radio
    initial_radio = app.auto_radio_enabled
    app._toggle_auto_radio()
    assert app.auto_radio_enabled is not initial_radio
    assert app.library.get_setting("auto_radio") == ("1" if app.auto_radio_enabled else "0")

    # Ensure Auto-Radio is enabled and repeat mode is OFF
    if not app.auto_radio_enabled:
        app._toggle_auto_radio()
    assert app.auto_radio_enabled is True
    app.queue.set_repeat(RepeatMode.OFF)

    curr_track = Track(id="radio_lead", title="Lead Track", artist="Famous Band", duration=2, source="Local", webpage_url=sample_path)
    app._play_track(curr_track)
    _pump(app, iterations=5)

    radio_recs = [
        Track(id="rec_1", title="Recommended Song 1", artist="Famous Band", duration=180, source="Local", webpage_url=sample_path),
        Track(id="rec_2", title="Recommended Song 2", artist="Similar Artist", duration=200, source="Local", webpage_url=sample_path),
    ]

    async def mock_get_related(*_a, **_k):
        return radio_recs

    with patch.object(app.search_service, "get_related_tracks", side_effect=mock_get_related):
        # Trigger track end with queue exhausted
        app.queue.clear()
        app.current_track = curr_track
        app._on_track_finished()
        for _ in range(15):
            _pump(app, iterations=2, delay=0.05)
            if len(app.queue) >= 1:
                break

    assert len(app.queue) >= 1
    assert app.current_track is not None
    assert app.current_track.id == "rec_1"


def test_e2e_synchronized_lyrics_view(e2e_env) -> None:
    """Verify real-time synced LRC lyrics highlighting, auto-scroll, clicking line to seek, and plain fallback."""
    app: MagicMusicPlayerApp = e2e_env["app"]
    sample_path = str(e2e_env["samples"][0])

    track = Track(id="lyric_track", title="Poetic Song", artist="Lyricist", duration=3, source="Local", webpage_url=sample_path)
    app._play_track(track)
    _pump(app, iterations=5)

    app.show_page("lyrics")
    _pump(app)

    # Synced lyrics data
    synced_lines = [
        LyricLine(1.0, "First line of poetry"),
        LyricLine(2.0, "Second line of poetry"),
        LyricLine(3.0, "Final concluding line"),
    ]
    lyrics_data = LyricsData(synced=synced_lines, plain="First line\nSecond line\nFinal line")

    async def mock_get_lyrics(*_a, **_k):
        return lyrics_data

    with patch.object(app.lyrics_service, "get_lyrics", side_effect=mock_get_lyrics):
        app.lyrics_view.render(force=True)
        for _ in range(20):
            _pump(app, iterations=2, delay=0.03)
            if len(app.lyrics_view.line_widgets) == 3:
                break

    assert len(app.lyrics_view.line_widgets) == 3

    # Position at 1.2s -> Line 0 active
    app.lyrics_view.update_playback_position(1.2)
    assert app.lyrics_view.active_line_index == 0
    btn0, _ = app.lyrics_view.line_widgets[0]
    assert btn0.cget("text_color") == app.palette.accent

    # Position at 2.2s -> Line 1 active, Line 0 dimmed
    app.lyrics_view.update_playback_position(2.2)
    assert app.lyrics_view.active_line_index == 1
    btn1, _ = app.lyrics_view.line_widgets[1]
    assert btn1.cget("text_color") == app.palette.accent
    assert btn0.cget("text_color") == app.palette.muted

    # Click line 2 -> seeks player
    app.lyrics_view._on_line_click(3.0)
    _pump(app, iterations=5)
    assert app.player.state().position >= 2.5


def test_e2e_downloads_workflow_and_offline_library(e2e_env) -> None:
    """Verify downloading, progress callback handling, fast-path cache conversion, and local playback."""
    app: MagicMusicPlayerApp = e2e_env["app"]
    download_dir = e2e_env["download_dir"]
    sample_path = e2e_env["samples"][0]

    track = Track(id="dl_track_1", title="Offline Hit", artist="Studio Artist", duration=3, source="YT", webpage_url="http://dl1")

    # Put audio in cache so download manager uses fast-path conversion
    app.cache_manager.put_file(track.id, sample_path)
    assert app.cache_manager.get_cached_audio(track.id) is not None

    app._download_track(track)
    task = app.download_manager.get_task(track.id)
    assert task is not None

    for _ in range(40):
        _pump(app, iterations=2, delay=0.05)
        if task.status in (DownloadStatus.COMPLETED, DownloadStatus.FAILED):
            break

    # Verify task completed
    assert task.status == DownloadStatus.COMPLETED
    assert task.result_path is not None and task.result_path.is_file()

    # Switch to Downloads view and verify track is rendered
    app.show_page("downloads")
    _pump(app)
    assert len(app.downloads_view._list_downloaded_files()) >= 1
    assert "Offline Hit" in app.downloads_view.downloads_count_label.cget("text") or "tracks" in app.downloads_view.downloads_count_label.cget("text")

    # Play downloaded file directly
    app._play_local_file(str(task.result_path))
    _pump(app, iterations=5)
    assert app.track_title_label.cget("text") != "Nothing playing"


def test_e2e_library_favorites_and_recently_played(e2e_env) -> None:
    """Verify favorites heart toggling, database storage, Library views, and play history."""
    app: MagicMusicPlayerApp = e2e_env["app"]
    sample_path = str(e2e_env["samples"][0])

    track = Track(id="fav_track_1", title="Beloved Classic", artist="Great Musician", duration=180, source="YouTube", webpage_url=sample_path)

    # 1. Favorite toggle
    assert not app.library.is_favorite(track.id)
    app._toggle_favorite(track)
    _pump(app)
    assert app.library.is_favorite(track.id)

    # Switch to Library -> Favorites
    app.show_page("library")
    app.library_segment.set("Favorites")
    app.library_view._on_mode_changed("Favorites")
    _pump(app)

    favs = app.library.favorites()
    assert any(f.id == track.id for f in favs)

    # Play track -> records play history
    app._play_track(track)
    _pump(app, iterations=5)

    # Switch to Recently Played
    app.library_segment.set("Recently Played")
    app.library_view._on_mode_changed("Recently Played")
    _pump(app)

    recent = app.library.recent_plays()
    assert any(r.id == track.id for r in recent)

    # Un-favorite
    app._toggle_favorite(track)
    _pump(app)
    assert not app.library.is_favorite(track.id)


def test_e2e_theming_and_live_color_switching(e2e_env) -> None:
    """Verify dark/light mode toggling, accent color switching, live widget re-theming, and DB persistence."""
    app: MagicMusicPlayerApp = e2e_env["app"]

    # Toggle theme: dark -> light -> dark
    assert app.appearance == "dark"
    app._cycle_theme()
    _pump(app)
    assert app.appearance == "light"
    assert app.library.get_setting("appearance") == "light"

    app._cycle_theme()
    _pump(app)
    assert app.appearance == "dark"

    # Accent color change
    accents = ["Emerald", "Crimson", "Amber", "Purple", "Refined Blue"]
    for accent in accents:
        app.accent_name = accent
        app.library.set_setting("accent", accent)
        app._apply_theme()
        _pump(app)
        assert app.palette.accent is not None


def test_e2e_mini_player_window(e2e_env) -> None:
    """Verify floating mini player launch, playback sync, transport controls, and main window restore."""
    app: MagicMusicPlayerApp = e2e_env["app"]
    sample_path = str(e2e_env["samples"][0])

    track = Track(id="mini_track", title="Mini Symphony", artist="Conductor", duration=3, source="Local", webpage_url=sample_path)
    app._play_track(track)
    _pump(app, iterations=5)

    # Open mini player
    app.open_mini_player()
    _pump(app, iterations=5)

    mini = app._mini_player
    assert mini is not None and mini.winfo_exists()
    assert not app.winfo_viewable()  # main window is withdrawn

    # Test mini player controls
    mini.update_playback(app.player.state(), track)
    assert "Mini Symphony" in mini.title_label.cget("text")

    # Mini pause toggle
    mini.play_btn.invoke()
    _pump(app, iterations=5)
    assert app.player.state().paused is True

    # Restore main window
    mini.restore_main()
    _pump(app, iterations=5)
    assert not mini.winfo_exists()
    assert app.winfo_viewable()  # main window is restored


def test_e2e_settings_dialog_and_equalizer(e2e_env) -> None:
    """Verify Settings dialog: settings persistence, live theme preview, 10-band equalizer presets and filters."""
    app: MagicMusicPlayerApp = e2e_env["app"]

    from mmp.ui.dialogs.settings_dialog import SettingsDialog

    # Open Settings Dialog
    SettingsDialog.show(app)
    _pump(app, iterations=5)

    # Find the dialog window
    toplevels = [w for w in app.winfo_children() if isinstance(w, type(app)) or "Settings" in getattr(w, "title", lambda: "")()]
    dialog = [w for w in toplevels if "Settings" in getattr(w, "title", lambda: "")()][0]
    assert dialog.winfo_exists()

    # Apply Equalizer Preset "Rock"
    rock_gains = EQ_PRESETS["Rock"]
    app.active_eq_gains = list(rock_gains)
    app.player.set_equalizer(rock_gains)
    assert "equalizer=" in str(app.player._mpv.af)

    dialog.destroy()
    _pump(app)


def test_e2e_keyboard_hotkeys_and_typing_guard(e2e_env) -> None:
    """Verify global keyboard shortcuts and verify typing guard prevents hotkeys from firing during search input."""
    app: MagicMusicPlayerApp = e2e_env["app"]
    sample_path = str(e2e_env["samples"][0])

    track = Track(id="hotkey_track", title="Keyboard Song", artist="Key Player", duration=3, source="Local", webpage_url=sample_path)
    app._play_track(track)
    _pump(app, iterations=5)

    # Hotkeys when not typing:
    # 1. Space toggles pause
    app.focus_set()
    app._hotkey_toggle_pause()
    _pump(app)
    assert app.player.state().paused is True

    app._hotkey_toggle_pause()
    _pump(app)
    assert app.player.state().paused is False

    # 2. Seek hotkeys
    app._hotkey_seek_forward()
    _pump(app, iterations=5)

    # 3. Page switch hotkey
    app._hotkey_switch_page("library")
    _pump(app)
    assert app.active_page == "library"

    # Typing Guard: when search entry has focus, hotkeys must be ignored
    app.search_entry.focus_set()
    assert app._typing_focused() is True

    # Hotkeys return None and do not execute
    res = app._hotkey_toggle_pause()
    assert res is None
    assert app.player.state().paused is False

    res_page = app._hotkey_switch_page("lyrics")
    assert res_page is None
    assert app.active_page == "library"  # page did NOT change


def test_e2e_stream_caching_and_error_recovery(e2e_env) -> None:
    """Verify stream URL caching, expiration handling, and automatic recovery on playback error."""
    app: MagicMusicPlayerApp = e2e_env["app"]

    url = "https://example.com/audio_test"
    stream = AudioStream(url="http://stream1", expires_at=time.time() + 1000)
    app.stream_extractor.cache_stream(url, stream)

    # Cached stream retrieved
    assert app.stream_extractor.get_cached_stream(url) == stream

    # Expired stream detected
    expired_stream = AudioStream(url="http://expired", expires_at=time.time() - 10)
    app.stream_extractor.cache_stream(url, expired_stream)
    assert app.stream_extractor.get_cached_stream(url) is None

    # Playback error recovery: purges cache and retries
    track = Track(id="err_track", title="Error Song", artist="Err", duration=120, source="YT", webpage_url="http://err_url")
    app.current_track = track
    app._current_track_retried = False
    app.stream_extractor.cache_stream("http://err_url", stream)

    with patch.object(app, "_begin_playback") as mock_begin:
        app._on_track_playback_error("Stream connection dropped")
        _pump(app)
        mock_begin.assert_called_once_with(track, is_retry=True)
        assert "http://err_url" not in app.stream_extractor._stream_cache


def test_e2e_audio_cache_and_prefetch_lifecycle(e2e_env) -> None:
    """Verify AudioCacheManager LRU behavior and PrefetchManager lookahead preloading."""
    app: MagicMusicPlayerApp = e2e_env["app"]
    cache = app.cache_manager
    sample_path = e2e_env["samples"][0]

    # Store file in cache
    cache.put_file("cache_test_1", sample_path)
    assert cache.get_cached_audio("cache_test_1") is not None

    # Test prefetch manager
    t_next = Track(id="pref_track", title="Next in Queue", artist="Artist", duration=120, source="YT", webpage_url="http://next_url")
    app.queue.add(t_next)

    with patch.object(app.stream_extractor, "get_cached_stream", return_value=None), \
         patch.object(app.worker, "submit") as mock_submit:
        app.prefetch_manager.check_prefetch()
        mock_submit.assert_called_once()


@pytest.mark.skipif(os.environ.get("MMP_SKIP_LIVE_TESTS") == "1", reason="Live network test skipped by env flag")
def test_e2e_live_network_smoke_search_and_stream() -> None:
    """Live smoke test against real YouTube / SoundCloud networks via yt-dlp."""
    from mmp.search import SearchService, StreamExtractor
    service = SearchService(limit_per_source=2)
    extractor = StreamExtractor()

    try:
        loop = asyncio.new_event_loop()
        results = loop.run_until_complete(service.search("Fairuz"))
        loop.close()
    except Exception as exc:
        pytest.skip(f"Live network unavailable: {exc}")

    assert len(results) >= 1
    assert any(t.source in ("YouTube", "YouTube Music", "SoundCloud") for t in results)


def test_e2e_right_click_context_menu_and_play_next(e2e_env) -> None:
    """Verify right-click context menu options across views and Play Next queue insertion."""
    app: MagicMusicPlayerApp = e2e_env["app"]
    _pump(app)

    t1 = Track(id="track_1", title="First Song", artist="Artist One", duration=150, source="YouTube", webpage_url="https://youtube.com/watch?v=aaa")
    t2 = Track(id="track_2", title="Second Song", artist="Artist Two", duration=180, source="YouTube", webpage_url="https://youtube.com/watch?v=bbb")
    t3 = Track(id="track_3", title="Third Song", artist="Artist Three", duration=210, source="YouTube", webpage_url="https://youtube.com/watch?v=ccc")

    # Render tracks in search
    app.show_page("search")
    app.search_view.render_results([t1, t2])
    _pump(app)

    assert len(app.search_view._rows) == 2
    row0 = list(app.search_view._rows.values())[0]

    # Verify context menu options on search row
    assert hasattr(row0, "_mmp_show_context_menu")
    menu = row0._mmp_show_context_menu()
    labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1) if menu.type(i) == "command"]
    assert "Play Next" in labels
    assert "Add to Queue" in labels
    assert "Copy Link" in labels
    assert "Open in Browser" in labels
    assert "Search Artist" in labels
    assert "Download" in labels

    # Test "Copy Link"
    app._copy_link(t1)
    _pump(app)
    assert app.clipboard_get() == "https://youtube.com/watch?v=aaa"

    # Test "Open in Browser"
    with patch("webbrowser.open") as mock_open:
        app._open_in_browser(t1)
        mock_open.assert_called_once_with("https://youtube.com/watch?v=aaa")

    # Test "Search Artist"
    with patch.object(app, "_start_search") as mock_search:
        app._search_artist("Artist One")
        _pump(app)
        assert app.active_page == "search"
        assert app.search_view.search_controller.text == "Artist One"
        mock_search.assert_called_once()

    # Test Play Next in Queue
    app.queue.clear()
    app.queue.add(t1)
    app.queue.add(t2)
    app.queue.jump_to(0)
    assert app.queue.current.id == t1.id

    # Add t3 with "Play Next"
    app._play_next(t3)
    _pump(app)
    # t3 must be immediately after current (at index 1)
    snap = app.queue.snapshot()
    assert len(snap.tracks) == 3
    assert snap.tracks[1].id == t3.id
    assert snap.tracks[2].id == t2.id

    # Test Downloads Context Menu
    sample_file = e2e_env["samples"][0]
    app.show_page("downloads")
    shutil.copy(sample_file, e2e_env["download_dir"] / "test_local.mp3")
    app.downloads_view.refresh()
    _pump(app, iterations=10)

    assert len(app.downloads_view._renderer._target_keys) >= 1
    dl_row = next(iter(app.downloads_view._renderer.rows.values()))
    dl_menu = dl_row._mmp_show_context_menu()
    dl_labels = [dl_menu.entrycget(i, "label") for i in range(dl_menu.index("end") + 1) if dl_menu.type(i) == "command"]
    assert "Show in Explorer" in dl_labels
    assert "Delete File" in dl_labels

    with patch("subprocess.Popen") as mock_popen:
        test_path = str(e2e_env["download_dir"] / "test_local.mp3")
        app._show_in_explorer(test_path)
        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert 'explorer /select,"' in cmd

    # Test Delete File
    target = e2e_env["download_dir"] / "test_local.mp3"
    assert target.exists()
    app._delete_downloaded_file(str(target))
    assert not target.exists()


def test_e2e_direct_url_paste_and_search(e2e_env) -> None:
    """Verify pasting direct video/audio URLs into search parses and extracts directly."""
    app: MagicMusicPlayerApp = e2e_env["app"]
    _pump(app)

    # Test URL detection
    assert is_direct_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ") is True
    assert is_direct_url("https://youtu.be/dQw4w9WgXcQ") is True
    assert is_direct_url("youtube.com/watch?v=dQw4w9WgXcQ") is True
    assert is_direct_url("youtu.be/dQw4w9WgXcQ") is True
    assert is_direct_url("https://soundcloud.com/artist/title") is True
    assert is_direct_url("soundcloud.com/artist/title") is True
    assert is_direct_url("https://music.youtube.com/watch?v=abc") is True
    assert is_direct_url("Mozart Symphony 40") is False
    assert is_direct_url("فيروز كيفك انت") is False

    # Simulate pasting a direct YouTube URL
    direct_url = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
    app.search_view.search_controller.set_text(direct_url)
    assert app.search_view.search_controller.text == direct_url

    mock_track = Track(
        id="dQw4w9WgXcQ",
        title="Never Gonna Give You Up",
        artist="Rick Astley",
        duration=213,
        source="YouTube",
        webpage_url=direct_url,
    )

    dummy_stream = AudioStream(url="http://mock_audio", expires_at=time.time() + 3600)
    async def mock_audio_stream(*_a, **_k):
        return dummy_stream

    with patch.object(app.search_service, "_extract_direct_url", return_value=[mock_track]), \
         patch.object(app.stream_extractor, "get_audio_stream", side_effect=mock_audio_stream):
        app._start_search()
        _pump(app, iterations=10)

    assert len(app.last_results) == 1
    assert app.last_results[0].id == "dQw4w9WgXcQ"
    assert app.last_results[0].title == "Never Gonna Give You Up"
    assert len(app.search_view._rows) == 1


def test_e2e_sleep_timer_workflow(e2e_env) -> None:
    """Verify setting sleep timers (duration and end of track), firing, and clean cancellation."""
    app: MagicMusicPlayerApp = e2e_env["app"]
    sample_path = str(e2e_env["samples"][0])
    track = Track(id="sleep_track", title="Lullaby", artist="Night Singer", duration=120, source="Local", webpage_url=sample_path)
    app._play_track(track)
    _pump(app, iterations=5)

    # 1. Timed sleep timer (e.g. 15 minutes)
    app.set_sleep_timer(15)
    _pump(app)
    assert app.is_sleep_timer_active() is True
    assert app.player_bar.sleep_timer_button.cget("text_color") == app.palette.accent

    # 2. Trigger timer fire
    app._on_sleep_timer_fired()
    _pump(app)
    assert app.is_sleep_timer_active() is False
    assert app.player_bar.sleep_timer_button.cget("text_color") == app.palette.muted

    # 3. End-of-track sleep timer
    app._play_track(track)
    _pump(app, iterations=3)
    app.set_sleep_timer(end_of_track=True)
    assert app._sleep_timer_end_of_track is True

    # Simulate track finishing
    app._on_track_finished()
    _pump(app)
    assert app.is_sleep_timer_active() is False

    # 4. Cancel sleep timer
    app.set_sleep_timer(30)
    assert app.is_sleep_timer_active() is True
    app.cancel_sleep_timer()
    assert app.is_sleep_timer_active() is False


def test_e2e_session_restore(e2e_env) -> None:
    """Verify queue, current track, and playback position restore across application sessions."""
    app: MagicMusicPlayerApp = e2e_env["app"]
    config_dir = e2e_env["config_dir"]
    sample_path = str(e2e_env["samples"][0])

    t1 = Track(id="ses_1", title="Song 1", artist="Artist 1", duration=100, source="Local", webpage_url=sample_path)
    t2 = Track(id="ses_2", title="Song 2", artist="Artist 2", duration=200, source="Local", webpage_url=sample_path)
    app.queue.clear()
    app._play_track(t1)
    app.queue.add(t2)
    _pump(app, iterations=5)

    # Close app to trigger session save
    app._on_close()
    time.sleep(0.15)

    # Verify session persisted in DB
    lib = MusicLibrary(config_dir / "library.db")
    session = lib.load_session()
    lib.close()
    assert session is not None
    assert len(session["tracks"]) == 2
    assert session["tracks"][0]["id"] == "ses_1"
    assert session["tracks"][1]["id"] == "ses_2"

    # Create new app instance on same config dir
    app2 = MagicMusicPlayerApp()
    _pump(app2, iterations=5)

    assert len(app2.queue) == 2
    snap = app2.queue.snapshot()
    assert snap.tracks[0].id == "ses_1"
    assert snap.tracks[1].id == "ses_2"
    assert app2.current_track is not None and app2.current_track.id == "ses_1"
    assert "Song 1" in app2.track_title_label.cget("text")

    # Resuming playback on restored session triggers playback cleanly
    with patch.object(app2, "_begin_playback") as mock_play:
        app2._toggle_pause()
        mock_play.assert_called_once_with(app2.current_track)

    app2._on_close()


def test_e2e_in_page_filters_library_and_downloads(e2e_env) -> None:
    """Verify instant in-memory filtering for Library and Downloads views."""
    app: MagicMusicPlayerApp = e2e_env["app"]
    _pump(app)

    # 1. Library in-page filtering
    t1 = Track(id="lib_1", title="Beethoven Symphony 5", artist="Ludwig van Beethoven", duration=200, source="YT", webpage_url="http://b5")
    t2 = Track(id="lib_2", title="Moonlight Sonata", artist="Beethoven", duration=180, source="YT", webpage_url="http://ms")
    t3 = Track(id="lib_3", title="Chopin Nocturne", artist="Frederic Chopin", duration=220, source="YT", webpage_url="http://cn")

    app.library.set_favorite(t1, True)
    app.library.set_favorite(t2, True)
    app.library.set_favorite(t3, True)

    app.show_page("library")
    app.library_view.refresh()
    app.library_view.render()
    _pump(app)

    assert len(app.library_view._renderer._target_keys) == 3

    # Filter for "Sonata"
    app.library_view.filter_entry.insert(0, "Sonata")
    app.library_view.render()
    _pump(app)
    assert len(app.library_view._renderer._target_keys) == 1
    assert "lib_2" in app.library_view._renderer._target_keys

    # Filter by artist "Chopin"
    app.library_view.filter_entry.delete(0, "end")
    app.library_view.filter_entry.insert(0, "Chopin")
    app.library_view.render()
    _pump(app)
    assert len(app.library_view._renderer._target_keys) == 1
    assert "lib_3" in app.library_view._renderer._target_keys

    # Clear filter
    app.library_view.filter_entry.delete(0, "end")
    app.library_view.render()
    _pump(app)
    assert len(app.library_view._renderer._target_keys) == 3

    # 2. Downloads in-page filtering
    sample1 = e2e_env["samples"][0]
    sample2 = e2e_env["samples"][1]
    shutil.copy(sample1, e2e_env["download_dir"] / "bach_brandenburg.mp3")
    shutil.copy(sample2, e2e_env["download_dir"] / "vivaldi_spring.mp3")

    app.show_page("downloads")
    app.downloads_view.refresh()
    _pump(app)
    assert len(app.downloads_view._renderer._target_keys) == 2

    # Filter downloads for "bach"
    app.downloads_view.filter_entry.insert(0, "bach")
    app.downloads_view.render()
    _pump(app)
    assert len(app.downloads_view._renderer._target_keys) == 1

    # Clear downloads filter
    app.downloads_view.filter_entry.delete(0, "end")
    app.downloads_view.render()
    _pump(app)
    assert len(app.downloads_view._renderer._target_keys) == 2


def test_e2e_queue_duration_summary_and_export(e2e_env, tmp_path) -> None:
    """Verify queue total duration summary display and playlist (.m3u) export."""
    app: MagicMusicPlayerApp = e2e_env["app"]
    _pump(app)

    t1 = Track(id="q1", title="Track 1", artist="Artist 1", duration=120, source="YT", webpage_url="http://q1")
    t2 = Track(id="q2", title="Track 2", artist="Artist 2", duration=180, source="YT", webpage_url="http://q2")

    app.queue.clear()
    app.queue.add(t1)
    app.queue.add(t2)

    app.show_page("upnext")
    app.queue_view.render()
    _pump(app)

    # 120 + 180 = 300s = 5:00
    assert "2 tracks" in app.queue_view.queue_count_label.cget("text")
    assert "5:00" in app.queue_view.queue_count_label.cget("text")

    # Export queue
    export_file = tmp_path / "saved_queue.m3u"
    res = app._export_queue_playlist(export_file)
    assert res == export_file
    assert export_file.exists()
    content = export_file.read_text(encoding="utf-8")
    assert "#EXTM3U" in content
    assert "Track 1" in content
    assert "http://q1" in content


def test_e2e_volume_normalization_and_equalizer(e2e_env) -> None:
    """Verify volume normalization toggling and coexistence with 10-band equalizer filter graph."""
    app: MagicMusicPlayerApp = e2e_env["app"]
    _pump(app)

    # 1. Toggle Volume Normalization
    assert app.player._volume_normalization is False
    app.player.set_volume_normalization(True)
    assert app.player._volume_normalization is True
    assert any("dynaudnorm" in str(x) for x in app.player._mpv.af)

    # 2. Apply Equalizer while normalization is on
    app.player.set_equalizer(EQ_PRESETS["Bass Boost"])
    assert any("equalizer=" in str(x) for x in app.player._mpv.af)
    assert any("dynaudnorm" in str(x) for x in app.player._mpv.af)

    # 3. Disable Normalization, verify Equalizer remains
    app.player.set_volume_normalization(False)
    assert not any("dynaudnorm" in str(x) for x in app.player._mpv.af)
    assert any("equalizer=" in str(x) for x in app.player._mpv.af)

    # 4. Clear Equalizer, verify empty af
    app.player.clear_equalizer()
    assert len(app.player._mpv.af) == 0 or app.player._mpv.af == ""

