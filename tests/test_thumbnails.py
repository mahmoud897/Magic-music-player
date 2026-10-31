from __future__ import annotations

from mmp.models import Track
from mmp.search import pick_thumbnail
from mmp.thumbnails import ThumbnailService, cover_resize_box


def make_track(n: int, thumb: str | None = None) -> Track:
    return Track(
        id=f"id{n}",
        title="Song",
        artist="A",
        duration=60,
        source="YouTube",
        webpage_url=f"url{n}",
        thumbnail_url=thumb,
    )


def test_cover_resize_box_wide_image() -> None:
    assert cover_resize_box(640, 360, 112) == (140, 0, 500, 360)


def test_cover_resize_box_tall_and_square() -> None:
    left, top, right, bottom = cover_resize_box(300, 500, 112)
    assert right - left == 300 and bottom - top == 300
    assert cover_resize_box(100, 100, 112) == (0, 0, 100, 100)


def test_cache_key_stable_and_distinct(tmp_path) -> None:
    service = ThumbnailService(tmp_path / "thumbs")
    a = service.cache_key(make_track(1))
    b = service.cache_key(make_track(1))
    c = service.cache_key(make_track(2))
    d = service.cache_key(Track("id1", "Song", "A", 60, "SoundCloud", "u1"))
    assert a == b
    assert a != c
    assert a != d


def test_disabled_without_pillow_or_url(tmp_path) -> None:
    service = ThumbnailService(tmp_path / "thumbs")
    no_thumb = make_track(1, thumb=None)
    assert service.cached_png(no_thumb) is None
    results = []
    service.load_async(no_thumb, worker=None, on_ready=lambda key, path: results.append(path))
    assert results == [None]
