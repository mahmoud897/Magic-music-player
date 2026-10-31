from __future__ import annotations

import asyncio
import time
from pathlib import Path

from mmp.search import AudioStream, StreamExtractor


def test_stream_is_expired() -> None:
    now = time.time()
    # Unexpired stream with future expiry
    stream1 = AudioStream(url="http://test/audio1", expires_at=now + 3600)
    assert not stream1.is_expired()

    # Expired stream with past expiry
    stream2 = AudioStream(url="http://test/audio2", expires_at=now - 10)
    assert stream2.is_expired()

    # Stream within buffer threshold (e.g. expires in 30s, buffer is 60s)
    stream3 = AudioStream(url="http://test/audio3", expires_at=now + 30)
    assert stream3.is_expired(buffer_seconds=60.0)


def test_stream_extractor_cache() -> None:
    extractor = StreamExtractor()
    url = "https://www.youtube.com/watch?v=mock123"

    assert extractor.get_cached_stream(url) is None

    stream = AudioStream(url="http://googlevideo.com/videoplayback?expire=9999999999", expires_at=time.time() + 3600)
    extractor.cache_stream(url, stream)

    cached = extractor.get_cached_stream(url)
    assert cached is not None
    assert cached.url == stream.url

    extractor.clear_cache()
    assert extractor.get_cached_stream(url) is None


def test_stream_extractor_local_bypass(tmp_path: Path) -> None:
    extractor = StreamExtractor()
    local_file = tmp_path / "song.mp3"
    local_file.write_bytes(b"mock audio bytes")

    # Fast path: local: prefix
    loop = asyncio.new_event_loop()
    stream1 = loop.run_until_complete(extractor.get_audio_stream(f"local:{local_file}"))
    assert stream1.url == str(local_file)
    assert stream1.headers == {}

    # Fast path: direct filesystem path
    stream2 = loop.run_until_complete(extractor.get_audio_stream(str(local_file)))
    assert stream2.url == str(local_file)
    loop.close()
