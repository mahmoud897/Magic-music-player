from __future__ import annotations

from mmp.arabic import (
    contains_arabic,
    display_text,
    is_arabic_char,
    search_text,
    visual_caret_position,
)
from mmp.app import table_text


def test_is_arabic_char_ranges() -> None:
    assert is_arabic_char("\u0641")  # ف
    assert is_arabic_char("\uFEFB")  # lam-alef presentation form
    assert not is_arabic_char("a")
    assert not is_arabic_char("")


def test_contains_arabic() -> None:
    assert contains_arabic("فيروز")
    assert contains_arabic("Fairuz فيروز")
    assert not contains_arabic("fairuz 2019")


def test_display_text_shapes_and_reorders_arabic() -> None:
    visual = display_text("فكر")
    assert visual != "فكر"
    assert any("\uFB50" <= c <= "\uFEFF" for c in visual)


def test_display_text_leaves_latin_untouched() -> None:
    assert display_text("Fairuz - Kifak Inta") == "Fairuz - Kifak Inta"


def test_search_text_restores_logical_order() -> None:
    assert search_text("ركف") == "فكر"


def test_roundtrip_through_display() -> None:
    for logical in ("فكر", "فيروز كيفك إنت", "لا إله إلا الله"):
        assert search_text(display_text(logical)) == logical


def test_lam_alef_ligature_roundtrip() -> None:
    shaped = display_text("لا")
    assert len(shaped) == 1  # merged into single ligature glyph
    assert search_text(shaped) == "لا"


def test_mixed_content_does_not_crash() -> None:
    mixed = display_text("فيروز - Kifak Inta (Official) 2019")
    assert "Kifak Inta" in mixed or "2019" in mixed
    assert search_text(mixed)


def test_table_text_applies_display_transform() -> None:
    out = table_text("فيروز - كيفك إنت", 80)
    assert any("\uFB50" <= c <= "\uFEFF" for c in out)
    assert table_text("plain latin title", 80) == "plain latin title"


def test_visual_caret_position_rules() -> None:
    assert visual_caret_position("") == 0
    assert visual_caret_position("فكر") == 0
    assert visual_caret_position("abc") == 3
    assert visual_caret_position("فيروز 2019") == 4
    assert visual_caret_position("فيروز ") == 0


def _type_string(text: str) -> str:
    """Mirror the app's keystroke math exactly: raw char inserts at the
    current caret, then the handler resyncs logical and re-renders shaped
    text, moving the caret per visual_caret_position."""
    content = ""
    caret = 0
    for char in text:
        raw = content[:caret] + char + content[caret:]
        logical = search_text(raw)
        content = display_text(logical)
        caret = visual_caret_position(logical)
    return content


def test_entry_model_arabic_words_render_shaped() -> None:
    content = _type_string("لا يوجد")
    assert content == display_text("لا يوجد")
    assert search_text(content) == "لا يوجد"


def test_entry_model_space_between_words_does_not_flip() -> None:
    """Regression: after a space the caret must return to 0, or the next
    letter lands between the space and the previous word and scrambles it."""
    content = _type_string("الحلقة و")
    assert search_text(content) == "الحلقة و"
    full = _type_string("الحلقة واحمد")
    assert search_text(full) == "الحلقة واحمد"


def test_entry_model_long_sentence() -> None:
    content = _type_string("لا يوجد شيء يستحق")
    assert search_text(content) == "لا يوجد شيء يستحق"


def test_entry_model_backspace_removes_newest_letter() -> None:
    content = display_text("الحلقة واحمد")
    for _ in range(5):  # remove "احمد" letter by letter
        logical = search_text(content)[:-1]
        content = display_text(logical)
    assert search_text(content) == "الحلقة "


def test_entry_model_mixed_arabic_digits() -> None:
    content = _type_string("فيروز 2019")
    assert search_text(content) == "فيروز 2019"
