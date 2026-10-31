from __future__ import annotations

import os
import time
from pathlib import Path

from mmp.cache_manager import AudioCacheManager


def test_audio_cache_store_and_retrieve(tmp_path: Path) -> None:
    cache = AudioCacheManager(cache_dir=tmp_path / "cache", max_size_bytes=100_000)
    source_file = tmp_path / "test.opus"
    source_file.write_bytes(b"A" * 5000)

    # Put in cache
    target = cache.put_file("yt:song123", source_file)
    assert target is not None
    assert target.is_file()

    # Retrieve from cache
    cached = cache.get_cached_audio("yt:song123")
    assert cached is not None
    assert cached.resolve() == target.resolve()

    # Stats
    stats = cache.stats()
    assert stats["count"] == 1
    assert stats["total_bytes"] == 5000


def test_audio_cache_lru_eviction(tmp_path: Path) -> None:
    # Set limit to hold about 2 files of 5000 bytes each
    cache = AudioCacheManager(cache_dir=tmp_path / "cache", max_size_bytes=11_000)

    f1 = tmp_path / "f1.m4a"
    f1.write_bytes(b"1" * 5000)
    f2 = tmp_path / "f2.m4a"
    f2.write_bytes(b"2" * 5000)
    f3 = tmp_path / "f3.m4a"
    f3.write_bytes(b"3" * 5000)

    cache.put_file("track1", f1)
    # Set f1's mtime to earlier in time
    c1 = cache.get_cached_audio("track1")
    assert c1 is not None
    os.utime(c1, (time.time() - 100, time.time() - 100))

    cache.put_file("track2", f2)
    assert cache.stats()["count"] == 2

    # Adding third file should trigger eviction of the oldest (track1)
    cache.put_file("track3", f3)
    assert cache.stats()["count"] <= 2
    assert cache.get_cached_audio("track1") is None
    assert cache.get_cached_audio("track3") is not None


def test_audio_cache_clear(tmp_path: Path) -> None:
    cache = AudioCacheManager(cache_dir=tmp_path / "cache")
    f = tmp_path / "test.m4a"
    f.write_bytes(b"X" * 6000)
    cache.put_file("trackA", f)
    assert cache.stats()["count"] == 1

    cache.clear()
    assert cache.stats()["count"] == 0
    assert cache.get_cached_audio("trackA") is None
