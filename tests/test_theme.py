from __future__ import annotations

from mmp.models import Track
from mmp.search import pick_thumbnail
from mmp.theme import (
    ACCENT_DEFS,
    PALETTE_TOKENS,
    accent_names,
    build_palette,
    default_accent,
)


def test_every_accent_builds_palettes_for_both_appearances() -> None:
    for appearance in ("dark", "light"):
        for accent in accent_names():
            palette = build_palette(appearance, accent)
            for token in PALETTE_TOKENS:
                value = getattr(palette, token)
                assert isinstance(value, str) and value.startswith("#"), (appearance, accent, token)


def test_unknown_values_fall_back_to_defaults() -> None:
    palette = build_palette("nonsense", "Not A Color")
    reference = build_palette("dark", default_accent())
    assert palette.bg == reference.bg


def test_refined_blue_is_the_default() -> None:
    assert default_accent() == "Refined Blue"
    assert "Refined Blue" in ACCENT_DEFS


def test_track_thumbnail_url_is_optional() -> None:
    track = Track("1", "Song", "Artist", 60, "YouTube", "https://example.test")
    assert track.thumbnail_url is None


def test_glyphs_and_fallbacks_coverage() -> None:
    from mmp.theme import GLYPHS, _ASCII_FALLBACKS, IconSheet

    sheet = IconSheet()
    for name in GLYPHS:
        assert name in _ASCII_FALLBACKS, f"Missing fallback for glyph: {name}"
        assert len(_ASCII_FALLBACKS[name]) > 0
        glyph = sheet.glyph(name)
        assert len(glyph) > 0

