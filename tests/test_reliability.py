from __future__ import annotations

import asyncio
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mmp.app import _set_windows_app_id
from mmp.downloader import DownloadManager, DownloadProgress, DownloadStatus
from mmp.library import MusicLibrary
from mmp.logging_config import get_logger, setup_logging
from mmp.models import Track
from mmp.search import AudioStream, StreamExtractor


def test_library_wal_mode_and_busy_timeout(tmp_path: Path) -> None:
    db_file = tmp_path / "test_wal.db"
    lib = MusicLibrary(db_file)

    # In SQLite, WAL mode on file-based DB returns 'wal'
    cursor = lib._conn.execute("PRAGMA journal_mode")
    journal_mode = cursor.fetchone()[0].lower()
    assert journal_mode == "wal"

    cursor = lib._conn.execute("PRAGMA busy_timeout")
    timeout = int(cursor.fetchone()[0])
    assert timeout >= 5000

    cursor = lib._conn.execute("PRAGMA synchronous")
    sync_mode = int(cursor.fetchone()[0])
    # 1 corresponds to NORMAL
    assert sync_mode == 1

    lib.close()


def test_audio_stream_expiry_detection() -> None:
    now = time.time()

    # Case 1: URL with explicit future expiration (e.g. 1 hour from now)
    stream_valid = AudioStream(url="https://example.com/audio", expires_at=now + 3600)
    assert not stream_valid.is_expired()

    # Case 2: URL expired 10 seconds ago
    stream_expired = AudioStream(url="https://example.com/audio", expires_at=now - 10)
    assert stream_expired.is_expired()

    # Case 3: URL expiring in 30 seconds, with 60-second safety buffer
    stream_near_expiry = AudioStream(url="https://example.com/audio", expires_at=now + 30)
    assert stream_near_expiry.is_expired(buffer_seconds=60)

    # Case 4: Default fallback expiration (5 hours)
    stream_old = AudioStream(url="https://example.com/audio", extracted_at=now - (6 * 3600))
    assert stream_old.is_expired()


def test_logging_configuration(tmp_path: Path, monkeypatch) -> None:
    # Set APP_DIR to temp directory
    monkeypatch.setattr("mmp.logging_config.APP_DIR", tmp_path)
    monkeypatch.setattr("mmp.logging_config._INITIALIZED", False)

    setup_logging()
    logger = get_logger("test_module")
    logger.info("Test message for MMP log verification")

    log_file = tmp_path / "mmp.log"
    assert log_file.exists()
    content = log_file.read_text(encoding="utf-8")
    assert "Test message for MMP log verification" in content
    assert "[mmp.test_module]" in content


def test_download_manager_queueing_and_concurrency(tmp_path: Path) -> None:
    track1 = Track(id="t1", title="Track 1", artist="Artist", duration=100, source="YT", webpage_url="http://1")
    track2 = Track(id="t2", title="Track 2", artist="Artist", duration=200, source="YT", webpage_url="http://2")
    track3 = Track(id="t3", title="Track 3", artist="Artist", duration=300, source="YT", webpage_url="http://3")

    completed_events: list[str] = []

    from concurrent.futures import Future

    class FakeWorker:
        def submit(self, coro, callback=None):
            # Synchronously resolve coroutine in test
            future: Future = Future()
            try:
                loop = asyncio.new_event_loop()
                result = loop.run_until_complete(coro)
                loop.close()
                future.set_result(result)
            except Exception as exc:
                future.set_exception(exc)
            if callback:
                callback(future)
            return future

    class FakeService:
        async def download(self, url: str, progress_callback):
            progress_callback(DownloadProgress("downloading", 50.0, "1 MB/s", "10s", "file.mp3"))
            progress_callback(DownloadProgress("processing", 100.0, "", "finalizing", "file.mp3"))
            return tmp_path / f"{Path(url).name}.mp3"

    manager = DownloadManager(
        service_factory=lambda: FakeService(),
        worker=FakeWorker(),
        max_concurrent=1,
    )

    def on_task_update(task):
        if task.status == DownloadStatus.COMPLETED:
            completed_events.append(task.track.id)

    manager.add_listener(on_task_update)

    manager.enqueue(track1)
    manager.enqueue(track2)
    manager.enqueue(track3)

    # All should have finished in sequence due to our synchronous mock worker
    assert "t1" in completed_events
    assert "t2" in completed_events
    assert "t3" in completed_events

    task1 = manager.get_task("t1")
    assert task1 is not None
    assert task1.status == DownloadStatus.COMPLETED
    assert task1.result_path == tmp_path / "1.mp3"

    active_cnt, queue_cnt, avg_pct = manager.aggregate_stats()
    assert active_cnt == 0
    assert queue_cnt == 0


def test_windows_app_id_safe() -> None:
    # Must execute safely across platforms
    _set_windows_app_id()


def test_theme_cycling_scrollable_frames_and_views(tmp_path: Path) -> None:
    import subprocess
    import sys

    src_dir = Path(__file__).resolve().parents[1] / "src"
    test_code = (
        "import sys\n"
        f"sys.path.insert(0, r'{src_dir}')\n"
        "from pathlib import Path\n"
        "from unittest.mock import MagicMock\n"
        "from mmp.models import Track\n"
        "import mmp.config\n"
        "import mmp.app\n"
        f"mmp.config.APP_DIR = Path(r'{tmp_path}')\n"
        f"mmp.app.APP_DIR = Path(r'{tmp_path}')\n"
        "mmp.app.AudioPlayer = MagicMock\n"
        "app = mmp.app.MagicMusicPlayerApp()\n"
        "app.withdraw()\n"
        "track1 = Track(id='t1', title='Adele - Hello', artist='Adele', duration=367, source='YouTube', webpage_url='http://1')\n"
        "app.last_results = [track1]\n"
        "app._render_search_results()\n"
        "app.library.set_favorite(track1, True)\n"
        "app.queue.add(track1)\n"
        "for _ in range(4):\n"
        "    app.update_idletasks()\n"
        "    rf = app.search_view.results_frame\n"
        "    canvas_bg = rf._parent_canvas.cget('bg')\n"
        "    frame_bg = rf.master.tk.call(rf._w, 'cget', '-bg')\n"
        "    row = rf.winfo_children()[0]\n"
        "    row_bg = row.cget('bg_color')\n"
        "    row_fg = row.cget('fg_color')\n"
        "    assert canvas_bg == app.palette.bg, f'{canvas_bg} != {app.palette.bg}'\n"
        "    assert frame_bg == app.palette.bg, f'{frame_bg} != {app.palette.bg}'\n"
        "    assert row_bg == app.palette.bg, f'{row_bg} != {app.palette.bg}'\n"
        "    assert row_fg == app.palette.surface_alt, f'{row_fg} != {app.palette.surface_alt}'\n"
        "    for page in ('library', 'downloads', 'upnext', 'lyrics', 'search'):\n"
        "        app.show_page(page)\n"
        "        app.update_idletasks()\n"
        "    app._cycle_theme()\n"
        "app.destroy()\n"
        "print('THEME_OK')\n"
    )

    proc = subprocess.run(
        [sys.executable, "-c", test_code],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"Error in theme test: {proc.stderr}\n{proc.stdout}"
    assert "THEME_OK" in proc.stdout


def test_mini_player_class_and_methods() -> None:
    from mmp.ui.dialogs.mini_player import MiniPlayerWindow

    assert hasattr(MiniPlayerWindow, "update_playback")
    assert hasattr(MiniPlayerWindow, "restore_main")
    assert hasattr(MiniPlayerWindow, "_start_drag")
    assert hasattr(MiniPlayerWindow, "_on_drag")
