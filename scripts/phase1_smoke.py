from __future__ import annotations

import asyncio
import sys
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".vendor"))
sys.path.insert(0, str(ROOT / "src"))

from mmp.search import SearchService, StreamExtractor


async def main() -> int:
    query = "fairuz"
    results = await SearchService(limit_per_source=2).search(query)
    print(f"Search results for {query!r}: {len(results)}")
    for track in results[:5]:
        print(f"- {track.title} | {track.artist} | {track.duration_label} | {track.source}")

    if results:
        stream_url = await StreamExtractor().get_audio_stream_url(results[0].webpage_url)
        print(f"Stream URL extracted: {stream_url[:80]}...")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
