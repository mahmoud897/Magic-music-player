from __future__ import annotations

from mmp.app import format_time, is_probably_arabic
from mmp.downloader import DownloadService
from mmp.models import Track


def test_duration_label_formats_minutes_and_hours() -> None:
    assert Track("1", "Song", "Artist", 65, "YouTube", "https://example.test").duration_label == "1:05"
    assert Track("2", "Song", "Artist", 3661, "YouTube", "https://example.test").duration_label == "1:01:01"


def test_unknown_duration_label() -> None:
    assert Track("1", "Song", "Artist", None, "YouTube", "https://example.test").duration_label == "--:--"


def test_arabic_detection() -> None:
    assert is_probably_arabic("فيروز")
    assert not is_probably_arabic("fairuz")


def test_time_formatting() -> None:
    assert format_time(0) == "0:00"
    assert format_time(125) == "2:05"
    assert format_time(3700) == "1:01:40"


def test_download_eta_and_speed_labels() -> None:
    assert DownloadService._format_eta(72) == "1m 12s"
    assert DownloadService._format_speed(2048) == "2.0 KB/s"
