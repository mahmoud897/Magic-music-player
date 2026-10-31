from __future__ import annotations

from mmp.search import pick_thumbnail


def test_prefers_direct_thumbnail_field() -> None:
    entry = {"thumbnail": "https://x/a.jpg", "thumbnails": [{"url": "https://x/big.jpg", "width": 1280}]}
    assert pick_thumbnail(entry) == "https://x/a.jpg"


def test_falls_back_to_artwork_url() -> None:
    assert pick_thumbnail({"artwork_url": "https://sc/art.jpg"}) == "https://sc/art.jpg"


def test_picks_smallest_reasonable_width() -> None:
    entry = {
        "thumbnails": [
            {"url": "https://x/huge.jpg", "width": 1280},
            {"url": "https://x/mid.jpg", "width": 480},
            {"url": "https://x/tiny.jpg", "width": 80},
        ]
    }
    assert pick_thumbnail(entry) == "https://x/mid.jpg"


def test_last_entry_when_no_widths() -> None:
    entry = {"thumbnails": [{"url": "https://x/1.jpg"}, {"url": "https://x/2.jpg"}]}
    assert pick_thumbnail(entry) == "https://x/2.jpg"


def test_none_for_junk_entries() -> None:
    assert pick_thumbnail({}) is None
    assert pick_thumbnail({"thumbnail": "not-a-url", "thumbnails": [{"url": ""}]}) is None
