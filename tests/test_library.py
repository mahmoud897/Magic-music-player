from __future__ import annotations

import pytest

from mmp.library import HISTORY_CAP, MusicLibrary
from mmp.models import Track


@pytest.fixture()
def library(tmp_path):
    lib = MusicLibrary(tmp_path / "library.db")
    yield lib
    lib.close()


def make_track(n: int) -> Track:
    return Track(id=f"id{n}", title=f"Song {n}", artist="A", duration=n, source="YouTube", webpage_url=f"url{n}")


def test_schema_is_reopenable(library: MusicLibrary, tmp_path) -> None:
    library.set_setting("volume", "80")
    library.record_play(make_track(1))

    reopened = MusicLibrary(tmp_path / "library.db")
    assert reopened.get_setting("volume") == "80"
    assert reopened.recent_plays()[0].id == "id1"
    reopened.close()


def test_upsert_updates_track_metadata(library: MusicLibrary) -> None:
    track = make_track(1)
    library.upsert_track(track)
    updated = Track(id=track.id, title="New", artist="B", duration=9, source="YouTube", webpage_url=track.webpage_url)
    library.upsert_track(updated)
    library.record_play(updated)

    plays = library.recent_plays()
    assert len(plays) == 1
    assert plays[0].title == "New"


def test_favorite_round_trip(library: MusicLibrary) -> None:
    a, b = make_track(1), make_track(2)
    library.set_favorite(a, True)
    library.set_favorite(b, True)
    assert library.is_favorite(a.id) and library.is_favorite(b.id)
    assert library.favorite_ids() == {"id1", "id2"}

    library.set_favorite(a, False)
    assert not library.is_favorite(a.id)
    assert [t.id for t in library.favorites()] == ["id2"]


def test_record_play_caps_history(library: MusicLibrary) -> None:
    for n in range(HISTORY_CAP + 25):
        library.record_play(make_track(n))
    plays = library.recent_plays(limit=HISTORY_CAP + 10)
    assert len(plays) <= HISTORY_CAP
    assert plays[0].id == f"id{HISTORY_CAP + 24}"


def test_recent_plays_dedupes_by_track_ordered_latest_first(library: MusicLibrary) -> None:
    library.record_play(make_track(1))
    library.record_play(make_track(2))
    library.record_play(make_track(1))
    plays = library.recent_plays()
    assert [t.id for t in plays] == ["id1", "id2"]


def test_kv_settings_round_trip_and_defaults(library: MusicLibrary) -> None:
    assert library.get_setting("missing") is None
    assert library.get_setting("missing", "fallback") == "fallback"
    library.set_setting("repeat", "all")
    library.set_setting("repeat", "one")
    assert library.get_setting("repeat") == "one"
