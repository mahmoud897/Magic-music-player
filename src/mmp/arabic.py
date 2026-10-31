from __future__ import annotations

import unicodedata

try:
    import arabic_reshaper
    from bidi.algorithm import get_display

    _AVAILABLE = True
except ImportError:  # pragma: no cover
    _AVAILABLE = False

ARABIC_CHAR_RANGES = (
    (0x0600, 0x06FF),
    (0x0750, 0x077F),
    (0x08A0, 0x08FF),
    (0xFB50, 0xFDFF),
    (0xFE70, 0xFEFF),
)


def is_arabic_char(char: str) -> bool:
    if not char:
        return False
    code = ord(char[0])
    return any(start <= code <= end for start, end in ARABIC_CHAR_RANGES)


def contains_arabic(text: str) -> bool:
    return any(is_arabic_char(char) for char in text)


def display_text(text: str) -> str:
    """Convert logical-order Arabic to shaped, visually-ordered text for Tk labels."""
    if not _AVAILABLE or not text or not contains_arabic(text):
        return text
    try:
        return get_display(arabic_reshaper.reshape(text))
    except Exception:
        return text


def search_text(text: str) -> str:
    """Convert visually-ordered entry text back to logical order for queries.

    Entry text is typed/pasted in visual order (see the caret handling in the
    UI), so running the bidi algorithm once more restores logical order.
    NFKC then folds ligatures/presentation forms back to base letters — after
    reordering, so lam-alef expands in the correct position.
    """
    if not _AVAILABLE or not text or not contains_arabic(text):
        return text
    try:
        return unicodedata.normalize("NFKC", get_display(text))
    except Exception:
        return text


def visual_caret_position(logical: str) -> int:
    """Caret index inside the shaped visual string for a logical caret at end.

    Arabic-ending text grows leftward, so the caret sits at index 0.
    A trailing LTR run (digits/Latin) after Arabic sits at the visual left,
    so the caret goes after that run. Pure LTR text ends at the right.
    """
    if not logical:
        return 0
    if is_arabic_char(logical[-1]):
        return 0
    index = len(logical)
    has_ltr = False
    while index > 0 and not is_arabic_char(logical[index - 1]):
        if logical[index - 1] not in " \t":
            has_ltr = True
        index -= 1
    if index == 0:
        return len(display_text(logical))
    if has_ltr:
        return len(display_text(logical[index:].replace(" ", "")))
    return 0
