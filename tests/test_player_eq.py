from __future__ import annotations

from mmp.player import EQ_BAND_COUNT, EQ_PRESETS, build_equalizer_af, normalize_eq_gains


def test_normalize_clamps_and_fills() -> None:
    gains = normalize_eq_gains([50.0, -99.0, "bad", None, float("nan")])
    assert gains[0] == 12.0
    assert gains[1] == -12.0
    assert gains[2] == 0.0
    assert gains[3] == 0.0
    assert gains[4] == 0.0
    assert len(gains) == EQ_BAND_COUNT


def test_normalize_truncates_extra_bands() -> None:
    gains = normalize_eq_gains([1.0] * 15)
    assert len(gains) == EQ_BAND_COUNT


def test_build_af_string_format() -> None:
    af = build_equalizer_af([0.0] * EQ_BAND_COUNT)
    assert af.startswith("lavfi=[")
    assert af.endswith("]")
    segments = af[len("lavfi=[") : -1].split(",")
    assert len(segments) == EQ_BAND_COUNT
    assert all(seg.startswith("equalizer=f=") for seg in segments)


def test_build_af_uses_lavfi_not_legacy_filter() -> None:
    """Regression: legacy `equalizer=...` hangs first playback in bundled mpv."""
    assert not build_equalizer_af([0.0] * EQ_BAND_COUNT).startswith("equalizer=")
    assert build_equalizer_af(EQ_PRESETS["Bass Boost"]).startswith("lavfi=[")


def test_all_presets_are_valid_ten_band_tuples() -> None:
    assert "Flat" in EQ_PRESETS
    for name, gains in EQ_PRESETS.items():
        normalized = normalize_eq_gains(gains)
        assert len(normalized) == EQ_BAND_COUNT
        assert all(-12.0 <= g <= 12.0 for g in normalized), name
