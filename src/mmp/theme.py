from __future__ import annotations

from dataclasses import dataclass

import customtkinter as ctk

APPEARANCES = ("dark", "light")

ACCENT_DEFS: dict[str, dict[str, str]] = {
    "Refined Blue": {
        "base": "#3a76ad",
        "hover": "#4f8ac0",
        "dark_subtle": "#152738",
        "light_subtle": "#ddeaf6",
    },
    "Violet": {
        "base": "#7557c9",
        "hover": "#8a70d8",
        "dark_subtle": "#241d3d",
        "light_subtle": "#e7e1f7",
    },
    "Teal": {
        "base": "#258f7d",
        "hover": "#37a693",
        "dark_subtle": "#122b27",
        "light_subtle": "#d8efeb",
    },
    "Amber": {
        "base": "#bd8630",
        "hover": "#cf9a44",
        "dark_subtle": "#2e2312",
        "light_subtle": "#f5ead4",
    },
}


@dataclass(frozen=True)
class Palette:
    bg: str
    surface: str
    surface_alt: str
    hover: str
    text: str
    muted: str
    idle: str
    idle_hover: str
    accent: str
    accent_hover: str
    accent_subtle: str


def accent_names() -> tuple[str, ...]:
    return tuple(ACCENT_DEFS)


PALETTE_TOKENS = tuple(Palette.__dataclass_fields__)


def default_accent() -> str:
    return "Refined Blue"


def build_palette(appearance: str, accent_name: str) -> Palette:
    accent = ACCENT_DEFS.get(accent_name, ACCENT_DEFS[default_accent()])
    if appearance == "light":
        return Palette(
            bg="#f3f5f8",
            surface="#ffffff",
            surface_alt="#fafbfc",
            hover="#e6ecf2",
            text="#19222c",
            muted="#5d6873",
            idle="#dbe1e8",
            idle_hover="#c9d2dc",
            accent=accent["base"],
            accent_hover=accent["hover"],
            accent_subtle=accent["light_subtle"],
        )
    return Palette(
        bg="#0f1216",
        surface="#161b21",
        surface_alt="#13181d",
        hover="#212932",
        text="#e7eaee",
        muted="#8b95a1",
        idle="#28303a",
        idle_hover="#333d49",
        accent=accent["base"],
        accent_hover=accent["hover"],
        accent_subtle=accent["dark_subtle"],
    )


GLYPHS = {
    "play": "\uE768",
    "pause": "\uE769",
    "prev": "\uE892",
    "next": "\uE893",
    "download": "\uE896",
    "heart": "\uE734",
    "heart_filled": "\uEB51",
    "settings": "\uE713",
    "search": "\uE721",
    "add": "\uE710",
    "close": "\uE8BB",
    "shuffle": "\uE14B",
    "repeat_all": "\uE8EE",
    "repeat_one": "\uE8ED",
    "volume": "\uE767",
    "volume_mute": "\uE74F",
    "music_note": "\uE8D6",
    "library": "\uE8F1",
    "folder": "\uE8B7",
    "refresh": "\uE72C",
    "brightness": "\uE706",
    "moon": "\uE708",
    "radio": "\uE7F6",
    "timer": "\uE916",
}

_ASCII_FALLBACKS = {
    "play": "\u25B6",
    "pause": "\u23F8",
    "prev": "|<",
    "next": ">|",
    "download": "\u2193",
    "heart": "\u2661",
    "heart_filled": "\u2665",
    "settings": "\u2699",
    "search": "\u2315",
    "add": "+",
    "close": "\u00D7",
    "shuffle": "\u292E",
    "repeat_all": "\u21BB",
    "repeat_one": "\u21BB1",
    "volume": "\u266B",
    "volume_mute": "\u266B\u00D7",
    "music_note": "\u266A",
    "library": "\u2261",
    "folder": "\u25A4",
    "refresh": "\u21BB",
    "brightness": "\u2600",
    "moon": "\u263D",
    "radio": "\u221E",
    "timer": "\u23F2",
}

_FONT_CANDIDATES = ("Segoe Fluent Icons", "Segoe MDL2 Assets")


class IconSheet:
    """Windows built-in icon fonts; falls back to unicode glyphs when absent."""

    def __init__(self) -> None:
        self.family: str | None = None
        self._fonts: dict[int, ctk.CTkFont] = {}
        try:
            import tkinter.font as tkfont

            families = set(tkfont.families())
        except Exception:
            families = set()
        for candidate in _FONT_CANDIDATES:
            if candidate in families:
                self.family = candidate
                break

    def available(self) -> bool:
        return self.family is not None

    def font(self, size: int) -> ctk.CTkFont:
        size = int(size)
        if size not in self._fonts:
            self._fonts[size] = ctk.CTkFont(family=self.family or "Segoe UI", size=size)
        return self._fonts[size]

    def glyph(self, name: str) -> str:
        if self.family is not None:
            return GLYPHS.get(name, "")
        return _ASCII_FALLBACKS.get(name, "")


def apply_appearance(appearance: str) -> None:
    ctk.set_appearance_mode("dark" if appearance != "light" else "light")
