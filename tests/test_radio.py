from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from mmp.models import Track
from mmp.search import SearchService


def test_get_related_tracks_query() -> None:
    service = SearchService()
    track = Track(id="yt1", title="Karma Police", artist="Radiohead", duration=260, source="YT", webpage_url="http://yt1")

    mock_results = [
        Track(id="yt1", title="Karma Police", artist="Radiohead", duration=260, source="YT", webpage_url="http://yt1"),
        Track(id="yt2", title="No Surprises", artist="Radiohead", duration=220, source="Radio", webpage_url="http://yt2"),
        Track(id="yt3", title="Paranoid Android", artist="Radiohead", duration=380, source="Radio", webpage_url="http://yt3"),
    ]

    with patch.object(service, "_search_source", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_results
        loop = asyncio.new_event_loop()
        related = loop.run_until_complete(service.get_related_tracks(track, limit=5))
        loop.close()

        mock_search.assert_called_once_with("ytsearch5:Radiohead audio", "Radio")
        # Ensure input track is filtered out from recommendations
        assert len(related) == 2
        assert related[0].id == "yt2"
        assert related[1].id == "yt3"
