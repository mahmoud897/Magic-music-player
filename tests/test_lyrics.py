from __future__ import annotations

from mmp.lyrics import LyricLine, LyricsService, clean_song_metadata, parse_lrc


def test_clean_song_metadata() -> None:
    t1, a1 = clean_song_metadata("Radiohead - Karma Police (Official Music Video)", "Radiohead")
    assert t1 == "Karma Police"
    assert a1 == "Radiohead"

    t2, a2 = clean_song_metadata("Creep [Official HD Video]", "Radiohead")
    assert t2 == "Creep"
    assert a2 == "Radiohead"

    t3, a3 = clean_song_metadata("Simple Song", "Artist")
    assert t3 == "Simple Song"
    assert a3 == "Artist"


def test_parse_lrc() -> None:
    lrc = """
    [00:05.12] First line of song
    [00:12.80] Second line
    [01:05.00] Chorus starts here
    """
    lines = parse_lrc(lrc)
    assert len(lines) == 3
    assert lines[0].timestamp == 5.12
    assert lines[0].text == "First line of song"
    assert lines[1].timestamp == 12.80
    assert lines[2].timestamp == 65.0
    assert lines[2].text == "Chorus starts here"


def test_find_active_line_index() -> None:
    service = LyricsService()
    lines = [
        LyricLine(timestamp=5.0, text="Intro"),
        LyricLine(timestamp=15.0, text="Verse 1"),
        LyricLine(timestamp=30.0, text="Chorus"),
    ]

    # Before first line
    assert service.find_active_line_index(lines, 2.0) == -1

    # At or after first line
    assert service.find_active_line_index(lines, 5.0) == 0
    assert service.find_active_line_index(lines, 10.0) == 0

    # At or after second line
    assert service.find_active_line_index(lines, 15.0) == 1
    assert service.find_active_line_index(lines, 25.0) == 1

    # At or after third line
    assert service.find_active_line_index(lines, 30.0) == 2
    assert service.find_active_line_index(lines, 120.0) == 2
