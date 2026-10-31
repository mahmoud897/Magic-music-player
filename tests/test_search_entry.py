# -*- coding: utf-8 -*-
from __future__ import annotations

from types import SimpleNamespace
import tkinter as tk

import pytest

from mmp.arabic import display_text, search_text
from mmp.search_entry import FakeKeyEvent, SearchEntryController


@pytest.fixture(scope="session")
def tk_root():
    root = tk.Tk()
    root.withdraw()
    yield root
    root.destroy()


@pytest.fixture()
def harness(tk_root):
    var = tk.StringVar()
    entry = tk.Entry(tk_root, textvariable=var)
    controller = SearchEntryController(entry, var)

    class Driver:
        def type_char(self, char: str) -> None:
            keysym = "space" if char == " " else "Arabic_x"
            event = FakeKeyEvent(keysym=keysym, char=char)
            if controller._on_key(event) != "break":
                pos = entry.index("insert")
                entry.insert(pos, char)
                entry.icursor(pos + len(char))

        def press(self, keysym: str, state: int = 0) -> str | None:
            return controller._on_key(FakeKeyEvent(keysym=keysym, state=state))

        def displace_mark(self, index) -> None:
            entry.icursor(index)

    yield Driver(), controller, var, entry
    entry.destroy()


def type_query(driver, query: str) -> None:
    for char in query:
        driver.type_char(char)


def test_typing_multiline_arabic_query(harness) -> None:
    driver, controller, var, _entry = harness
    expected = "فيروز كيفك احمد"
    type_query(driver, expected)
    assert controller.text == expected
    assert var.get() == display_text(expected)


def test_displaced_mark_never_corrupts_text(harness) -> None:
    """Regression for the reported bug: the old design scrambled everything
    after the first space whenever the insert mark moved. The model must be
    immune to mark displacement."""
    driver, controller, var, entry = harness
    expected = ""
    for index, char in enumerate("فيروز كيفك"):
        driver.displace_mark("end" if index % 2 else 0)
        driver.type_char(char)
        expected += char
        assert controller.text == expected
    assert search_text(var.get()) == expected


def test_backspace_removes_newest_letter(harness) -> None:
    driver, controller, var, _entry = harness
    type_query(driver, "الحلقة واحمد")
    for _ in range(5):
        assert driver.press("BackSpace") == "break"
    assert controller.text == "الحلقة "
    assert var.get() == display_text("الحلقة ")


def test_backspace_empty_is_noop(harness) -> None:
    driver, controller, _var, _entry = harness
    assert driver.press("BackSpace") == "break"
    assert controller.text == ""


def test_delete_key_removes_ahead_of_caret(harness) -> None:
    driver, controller, _var, _entry = harness
    type_query(driver, "فيروز")
    driver.press("Home")
    driver.press("Delete")
    assert controller.text == "يروز"


def test_home_end_navigation(harness) -> None:
    driver, controller, _var, entry = harness
    type_query(driver, "فيروز")
    driver.press("Home")
    driver.type_char("ا")
    assert controller.text == "افيروز"
    driver.press("End")
    driver.type_char("ن")
    assert controller.text == "افيروzn".replace("zn", "زن")


def test_arrow_keys_move_logical_caret(harness) -> None:
    driver, controller, _var, _entry = harness
    type_query(driver, "\u0643\u064a\u0641")          # كيف
    driver.press("Right")
    driver.type_char("\u0627")                        # ا
    assert controller.text == "\u0643\u064a\u0627\u0641"   # ك ي ا ف
    driver.press("End")
    driver.type_char("\u0646")                        # ن
    assert controller.text == "\u0643\u064a\u0627\u0641\u0646"  # ك ي ا ف ن


def test_paste_appends_to_model(harness) -> None:
    driver, controller, var, entry = harness
    type_query(driver, "فيروز ")
    entry.clipboard_clear()
    entry.clipboard_append("كيفك إنت")
    entry.update()
    assert controller._on_paste(SimpleNamespace()) == "break"
    assert controller.text == "فيروز كيفك إنت"
    assert search_text(var.get()) == "فيروز كيفك إنت"


def test_mixed_digits_and_latin(harness) -> None:
    driver, controller, _var, _entry = harness
    type_query(driver, "فيروز 2019 live")
    assert controller.text == "فيروز 2019 live"


def test_lam_alef_words_stay_intact(harness) -> None:
    driver, controller, _var, _entry = harness
    type_query(driver, "الحلقة جامدة لا")
    assert controller.text == "الحلقة جامدة لا"


def test_select_all_then_type_replaces_everything(harness) -> None:
    driver, controller, _var, entry = harness
    type_query(driver, "فيروز كيفك")
    entry.select_range(0, "end")
    entry.update()
    driver.type_char("ش")
    assert controller.text == "ش"


def test_ctrl_z_undoes_through_model_not_widget(harness) -> None:
    driver, controller, var, _entry = harness
    type_query(driver, "\u0641\u064a\u0631\u0648\u0632")
    assert driver.press("z", state=CTRL) == "break"
    assert controller.text == ""
    assert var.get() == display_text("")


CTRL = 0x0004


def test_ctrl_a_selects_all_and_typing_replaces(harness) -> None:
    driver, controller, _var, entry = harness
    type_query(driver, "\u0641\u064a\u0631\u0648\u0632 \u0643\u064a\u0641\u0643")
    assert driver.press("a", state=CTRL) == "break"
    assert entry.select_present()
    driver.type_char("\u0634")
    assert controller.text == "\u0634"


def test_ctrl_backspace_deletes_previous_word(harness) -> None:
    driver, controller, _var, _entry = harness
    type_query(driver, "\u0641\u064a\u0631\u0648\u0632 \u0643\u064a\u0641\u0643")
    driver.press("BackSpace", state=CTRL)
    assert controller.text == "\u0641\u064a\u0631\u0648\u0632"
    driver.press("BackSpace", state=CTRL)
    assert controller.text == ""


def test_ctrl_delete_deletes_next_word(harness) -> None:
    driver, controller, _var, _entry = harness
    type_query(driver, "\u0641\u064a\u0631\u0648\u0632 \u0643\u064a\u0641\u0643 \u0627\u062d\u0645\u062f")
    driver.press("Home")
    driver.press("Delete", state=CTRL)
    assert controller.text == "\u0643\u064a\u0641\u0643 \u0627\u062d\u0645\u062f"


def test_undo_reverts_typing_and_redo_restores(harness) -> None:
    driver, controller, _var, _entry = harness
    for ch in "abc":
        driver.type_char(ch)
    assert driver.press("z", state=CTRL) == "break"
    assert controller.text == ""
    assert driver.press("y", state=CTRL) == "break"
    assert controller.text == "abc"


def test_undo_reverts_paste(harness) -> None:
    driver, controller, _var, entry = harness
    entry.clipboard_clear()
    entry.clipboard_append("\u0643\u064a\u0641\u0643")
    entry.update()
    controller._on_paste(SimpleNamespace())
    assert controller.text == "\u0643\u064a\u0641\u0643"
    driver.press("z", state=CTRL)
    assert controller.text == ""
    driver.press("y", state=CTRL)
    assert controller.text == "\u0643\u064a\u0641\u0643"


def test_undo_reverts_ctrl_backspace(harness) -> None:
    driver, controller, _var, _entry = harness
    type_query(driver, "\u0641\u064a\u0631\u0648\u0632 \u0643\u064a\u0641\u0643")
    driver.press("BackSpace", state=CTRL)
    assert controller.text == "\u0641\u064a\u0631\u0648\u0632"
    driver.press("z", state=CTRL)
    assert controller.text == "\u0641\u064a\u0631\u0648\u0632 \u0643\u064a\u0641\u0643"


def test_escape_clears_field_and_is_undoable(harness) -> None:
    driver, controller, _var, _entry = harness
    type_query(driver, "\u0641\u064a\u0631\u0648\u0632")
    assert driver.press("Escape") == "break"
    assert controller.text == ""
    driver.press("z", state=CTRL)
    assert controller.text == "\u0641\u064a\u0631\u0648\u0632"
