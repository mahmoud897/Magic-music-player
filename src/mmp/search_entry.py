from __future__ import annotations

import time
import tkinter as tk

from .arabic import (
    contains_arabic,
    display_text,
    search_text,
    visual_caret_position,
)

_SHIFT_MASK = 0x0001
_CTRL_MASK = 0x0004


class FakeKeyEvent:
    """Duck-typed stand-in for tk.Event so tests can drive the controller."""

    def __init__(self, keysym: str = "", char: str = "", state: int = 0) -> None:
        self.keysym = keysym
        self.char = char
        self.state = state


class SearchEntryController:
    """Owns the logical query text and projects it onto a Tk entry widget.

    The entry widget is treated as a read-only view: every edit is applied to
    an internal logical-order buffer with its own logical caret, then the
    shaped visual form is written back to the widget. Because the widget
    content is never parsed back, displaced carets, selections or platform
    quirks can never corrupt the text.
    """

    def __init__(self, entry: object, var: tk.StringVar) -> None:
        self._entry = entry
        self._var = var
        self._logical = ""
        self._caret = 0
        self._undo: list[tuple[str, int]] = []
        self._redo: list[tuple[str, int]] = []
        self._undo_stamp = 0.0
        self._undo_mergeable = False
        self._attach()

    @property
    def text(self) -> str:
        return self._logical

    def set_text(self, text: str) -> None:
        if text != self._logical:
            self._snapshot(mergeable=False)
        self._logical = text
        self._caret = len(text)
        self._project()

    def clear(self) -> None:
        self.set_text("")

    # -------------------------------------------------------- undo/redo

    def _snapshot(self, mergeable: bool) -> None:
        now = time.monotonic()
        if not (
            mergeable
            and self._undo_mergeable
            and self._undo
            and now - self._undo_stamp < 0.7
        ):
            self._undo.append((self._logical, self._caret))
            del self._undo[:-200]
        self._undo_stamp = now
        self._undo_mergeable = mergeable
        self._redo.clear()

    def _undo_step(self) -> None:
        if not self._undo:
            return
        self._redo.append((self._logical, self._caret))
        self._logical, self._caret = self._undo.pop()
        self._undo_mergeable = False
        self._project()

    def _redo_step(self) -> None:
        if not self._redo:
            return
        self._undo.append((self._logical, self._caret))
        self._logical, self._caret = self._redo.pop()
        self._undo_mergeable = False
        self._project()

    # ------------------------------------------------------------- wiring

    def _attach(self) -> None:
        entry = self._entry
        entry.bind("<Key>", self._on_key)
        entry.bind("<<Paste>>", self._on_paste)
        entry.bind("<<Copy>>", self._on_copy)
        entry.bind("<<Cut>>", self._on_cut)
        entry.bind("<ButtonRelease-1>", self._on_click)

    # -------------------------------------------------------- key routing

    def _on_key(self, event) -> str | None:
        keysym = getattr(event, "keysym", "") or ""
        char = getattr(event, "char", "") or ""
        state = int(getattr(event, "state", 0) or 0)
        ctrl = bool(state & _CTRL_MASK)

        if keysym == "BackSpace":
            if ctrl:
                self._delete_word_back()
            else:
                self._backspace()
            return "break"
        if keysym in ("Delete", "KP_Delete"):
            if ctrl:
                self._delete_word_ahead()
            else:
                self._delete_ahead()
            return "break"
        if keysym == "Home" and not state & _SHIFT_MASK:
            self._caret = 0
            self._project()
            return "break"
        if keysym == "End" and not state & _SHIFT_MASK:
            self._caret = len(self._logical)
            self._project()
            return "break"
        if keysym in ("Left", "Right") and not state & _SHIFT_MASK:
            self._step(keysym)
            return "break"
        if keysym in ("Up", "Down", "Return", "Tab"):
            return None
        if keysym == "Escape":
            if self._logical:
                self.clear()
                return "break"
            return None
        if ctrl and keysym.lower() == "a":
            try:
                self._entry.select_range(0, "end")
                self._entry.icursor("end")
            except Exception:
                pass
            return "break"
        if ctrl and keysym.lower() == "z":
            if state & _SHIFT_MASK:
                self._redo_step()
            else:
                self._undo_step()
            return "break"
        if ctrl and keysym.lower() == "y":
            self._redo_step()
            return "break"
        if char and char[0] >= " ":
            self._insert(char)
            return "break"
        return None

    def _delete_word_back(self) -> None:
        if not self._remove_selection():
            if self._caret == 0:
                return
            index = self._caret
            while index > 0 and not self._logical[index - 1].isspace():
                index -= 1
            while index > 0 and self._logical[index - 1].isspace():
                index -= 1
            self._snapshot(mergeable=False)
            self._logical = self._logical[:index] + self._logical[self._caret :]
            self._caret = index
        self._project()

    def _delete_word_ahead(self) -> None:
        if not self._remove_selection():
            length = len(self._logical)
            if self._caret >= length:
                return
            index = self._caret
            while index < length and self._logical[index].isspace():
                index += 1
            while index < length and not self._logical[index].isspace():
                index += 1
            while index < length and self._logical[index].isspace():
                index += 1
            self._snapshot(mergeable=False)
            self._logical = self._logical[: self._caret] + self._logical[index :]
        self._project()

    def _step(self, keysym: str) -> None:
        rtl = contains_arabic(self._logical)
        forward = (keysym == "Left") if rtl else (keysym == "Right")
        if forward:
            self._caret = min(len(self._logical), self._caret + 1)
        else:
            self._caret = max(0, self._caret - 1)
        self._project()

    # ------------------------------------------------------------ editing

    def _insert(self, text: str) -> None:
        if not text:
            return
        self._snapshot(mergeable=True)
        self._remove_selection()
        caret = self._caret
        self._logical = self._logical[:caret] + text + self._logical[caret:]
        self._caret = caret + len(text)
        self._project()

    def _backspace(self) -> None:
        span = self._selection_span()
        if span is not None or self._caret > 0:
            self._snapshot(mergeable=True)
        if self._remove_selection():
            self._project()
            return
        if self._caret > 0:
            before = self._caret - 1
            self._logical = self._logical[:before] + self._logical[self._caret :]
            self._caret = before
            self._project()

    def _delete_ahead(self) -> None:
        span = self._selection_span()
        if span is not None or self._caret < len(self._logical):
            self._snapshot(mergeable=True)
        if self._remove_selection():
            self._project()
            return
        if self._caret < len(self._logical):
            self._logical = self._logical[: self._caret] + self._logical[self._caret + 1 :]
            self._project()

    # ---------------------------------------------------------- clipboard

    def _on_paste(self, _event) -> str:
        try:
            clip = self._entry.clipboard_get()
        except Exception:
            return "break"
        text = clip.strip()
        if text:
            self._insert(text)
        return "break"

    def _on_copy(self, _event) -> str:
        try:
            selected = self._entry.selection_get()
        except Exception:
            return "break"
        if selected:
            self._entry.clipboard_clear()
            self._entry.clipboard_append(search_text(selected))
        return "break"

    def _on_cut(self, _event) -> str:
        self._on_copy(_event)
        if self._selection_span() is not None:
            self._snapshot(mergeable=False)
            if self._remove_selection():
                self._project()
        return "break"

    def _selection_span(self) -> tuple[int, int] | None:
        try:
            if not self._entry.select_present():
                return None
            selected = search_text(self._entry.selection_get())
        except Exception:
            return None
        if not selected:
            return None
        start = self._logical.find(selected)
        if start < 0:
            return None
        return start, start + len(selected)

    def _remove_selection(self) -> bool:
        span = self._selection_span()
        if span is None:
            return False
        start, end = span
        self._logical = self._logical[:start] + self._logical[end:]
        self._caret = start
        return True

    # --------------------------------------------------------- projection

    def _on_click(self, _event) -> None:
        try:
            self._entry.after_idle(self._project)
        except Exception:
            self._project()

    def _project(self) -> None:
        visual = display_text(self._logical)
        try:
            if self._var.get() != visual:
                self._var.set(visual)
            desired_justify = "right" if contains_arabic(self._logical) else "left"
            if getattr(self, "_current_justify", None) != desired_justify:
                self._entry.configure(justify=desired_justify)
                self._current_justify = desired_justify
            self._entry.select_clear()
        except Exception:
            pass
        self._park()

    def _park(self) -> None:
        limit = max(len(display_text(self._logical)), len(self._var.get()))
        if self._caret >= len(self._logical):
            position = visual_caret_position(self._logical)
        else:
            position = len(display_text(self._logical[: self._caret]))
        try:
            self._entry.icursor(max(0, min(position, limit)))
        except Exception:
            pass
