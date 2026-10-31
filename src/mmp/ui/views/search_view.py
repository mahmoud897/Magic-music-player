from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

import customtkinter as ctk

from ...search_entry import SearchEntryController
from ..components.track_row import TrackRow

if TYPE_CHECKING:
    from ...app import MagicMusicPlayerApp
    from ...models import Track


class SearchView:
    """Manages the music search interface and results list."""

    def __init__(self, app: MagicMusicPlayerApp, parent: ctk.CTkFrame) -> None:
        self.app = app
        self.parent = parent
        self._build_ui()

    def _build_ui(self) -> None:
        self.parent.grid_columnconfigure(0, weight=1)
        self.parent.grid_rowconfigure(1, weight=1)

        top = ctk.CTkFrame(self.parent, fg_color="transparent")
        top.grid(row=0, column=0, sticky="ew", padx=22, pady=(18, 6))
        top.grid_columnconfigure(0, weight=1)

        entry_wrap = ctk.CTkFrame(top, fg_color="transparent")
        entry_wrap.grid(row=0, column=0, padx=(0, 10), sticky="ew")
        entry_wrap.grid_columnconfigure(0, weight=1)

        self.search_var = tk.StringVar()
        self.search_entry = ctk.CTkEntry(
            entry_wrap,
            textvariable=self.search_var,
            height=42,
            corner_radius=21,
            placeholder_text="Search music  \u00b7  Arabic supported",
            font=ctk.CTkFont(size=14),
            fg_color=self.app.palette.surface,
            text_color=self.app.palette.text,
            border_color=self.app.palette.idle,
            placeholder_text_color=self.app.palette.muted,
        )
        self.search_entry.grid(row=0, column=0, sticky="ew")
        self.app._themed(
            self.search_entry,
            fg_color="surface",
            text_color="text",
            border_color="idle",
            placeholder_text_color="muted",
        )

        self.clear_search_button = ctk.CTkButton(
            entry_wrap,
            text="\u2715",
            width=28,
            height=28,
            corner_radius=14,
            fg_color="transparent",
            hover_color=self.app.palette.hover,
            text_color=self.app.palette.muted,
            font=ctk.CTkFont(size=12, weight="bold"),
            command=self._on_clear_search,
        )
        self.clear_search_button.grid(row=0, column=1, padx=(6, 0))
        self.app._themed(self.clear_search_button, hover_color="hover", text_color="muted")

        self.search_controller = SearchEntryController(self.search_entry, self.search_var)
        self.search_entry.bind("<Return>", lambda _event: self.app._on_search_return())

        self.search_button = ctk.CTkButton(
            top,
            text="Search",
            width=110,
            height=42,
            corner_radius=21,
            font=ctk.CTkFont(size=13, weight="bold"),
            text_color="#ffffff",
            command=self.app._start_search,
        )
        self.search_button.grid(row=0, column=1)
        self.app._themed(self.search_button, fg_color="accent", hover_color="accent_hover")

        self.recent_frame = ctk.CTkFrame(top, fg_color="transparent")
        self.recent_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        self._recent_label = ctk.CTkLabel(
            self.recent_frame,
            text="Recent",
            font=ctk.CTkFont(size=11),
            text_color=self.app.palette.muted,
        )
        self.app._themed(self._recent_label, text_color="muted")
        self._recent_buttons: list[ctk.CTkButton] = []
        for _ in range(5):
            button = ctk.CTkButton(
                self.recent_frame,
                text="",
                width=80,
                height=26,
                corner_radius=13,
                font=ctk.CTkFont(size=11),
                fg_color=self.app.palette.idle,
                hover_color=self.app.palette.idle_hover,
                text_color=self.app.palette.text,
            )
            self.app._themed(button, fg_color="idle", hover_color="idle_hover", text_color="text")
            self._recent_buttons.append(button)
        self._clear_recent_button = ctk.CTkButton(
            self.recent_frame,
            text="Clear",
            width=44,
            height=26,
            corner_radius=13,
            font=ctk.CTkFont(size=11),
            fg_color="transparent",
            hover_color=self.app.palette.hover,
            text_color=self.app.palette.muted,
            command=self.app._clear_recent_searches,
        )
        self.app._themed(self._clear_recent_button, hover_color="hover", text_color="muted")
        self._render_recent_searches()

        self.provider_progress_frame = ctk.CTkFrame(top, fg_color="transparent")
        self.provider_progress_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self._provider_labels: dict[str, ctk.CTkLabel] = {}
        for provider in ("YouTube", "YouTube Music", "SoundCloud"):
            label = ctk.CTkLabel(
                self.provider_progress_frame,
                text=provider,
                font=ctk.CTkFont(size=11),
                text_color=self.app.palette.muted,
            )
            self.app._themed(label, text_color="muted")
            label.pack(side="left", padx=(2, 12))
            self._provider_labels[provider] = label
        self._provider_status: dict[str, tuple[str, int, float | None]] = {}

        self.results_frame = ctk.CTkScrollableFrame(self.parent, fg_color=self.app.palette.bg)
        self.results_frame.grid(row=1, column=0, sticky="nsew", padx=14, pady=(4, 10))
        self.app._themed(self.results_frame, fg_color="bg")
        self._rows: dict[str, ctk.CTkFrame] = {}
        self._empty_label: ctk.CTkLabel | None = None
        self._empty_message: str | None = None

    def _render_recent_searches(self) -> None:
        queries = self.app.recent_searches[:5]
        if not queries:
            self.recent_frame.grid_remove()
            return
        self.recent_frame.grid()
        self._recent_label.pack(side="left", padx=(2, 7))
        self._clear_recent_button.pack(side="right", padx=(4, 0))
        for index, button in enumerate(self._recent_buttons):
            if index < len(queries):
                query = queries[index]
                label = query if len(query) <= 22 else query[:19] + "…"
                button.configure(
                    text=label,
                    width=min(160, max(76, len(label) * 7 + 22)),
                    command=lambda value=query: self._use_recent_search(value),
                )
                button.pack(side="left", padx=(0, 5))
            else:
                button.pack_forget()

    def refresh_recent_searches(self) -> None:
        self._render_recent_searches()

    def _use_recent_search(self, query: str) -> None:
        self.search_controller.set_text(query)
        self.app._start_search()

    def _on_clear_search(self) -> None:
        self.search_controller.clear()
        self.search_entry.focus_set()

    def set_provider_status(self, provider: str, state: str, result_count: int = 0, duration: float | None = None) -> None:
        self._provider_status[provider] = (state, result_count, duration)
        label = self._provider_labels.get(provider)
        if label is None:
            return
        color = self.app.palette.muted
        if state == "searching":
            text = f"{provider} · searching"
            color = self.app.palette.accent
        elif state == "done" and result_count:
            text = f"{provider} · {result_count}"
            color = self.app.palette.text
        elif state == "done":
            text = f"{provider} · no matches"
        elif state == "failed":
            text = f"{provider} · unavailable"
        else:
            text = provider
        if label.cget("text") != text:
            label.configure(text=text, text_color=color)

    def reset_provider_status(self) -> None:
        for provider in self._provider_labels:
            self.set_provider_status(provider, "searching")

    def render_results(self, tracks: list[Track], message: str | None = None) -> None:
        hooks_by_context = getattr(self.app, "_row_repaint_hooks_by_context", None)
        if hooks_by_context is not None:
            hooks = hooks_by_context.setdefault("search", [])
            hooks.clear()
        else:
            self.app._row_repaint_hooks = []
        if message:
            self._discard_rows()
            self._empty_state(message)
            return
        if not tracks:
            self._discard_rows()
            self._empty_state("Search for a track to begin.\nResults appear here.")
            return
        self._clear_empty()
        target_keys: set[str] = set()
        for track in tracks:
            target_keys.add(track.webpage_url or track.id)
        for key in tuple(self._rows):
            if key not in target_keys:
                self._rows.pop(key).destroy()

        for row_index, track in enumerate(tracks):
            key = track.webpage_url or track.id
            row = self._rows.get(key)
            if row is None:
                row = TrackRow.create(self.app, self.results_frame, track, context="search", index=row_index)
                self._rows[key] = row
            else:
                TrackRow.update(self.app, row, track, "search", row_index)
                entry = getattr(row, "_mmp_repaint_entry", None)
                if hooks_by_context is not None and entry is not None:
                    hooks_by_context["search"].append(entry)

    def _empty_state(self, message: str) -> None:
        if self._empty_label is not None and self._empty_message == message:
            return
        self._clear_empty()
        self._empty_message = message
        self._empty_label = ctk.CTkLabel(
            self.results_frame,
            text=message,
            font=ctk.CTkFont(size=13),
            text_color=self.app.palette.muted,
            justify="center",
        )
        self.app._themed(self._empty_label, text_color="muted")
        self._empty_label.grid(row=0, column=0, sticky="nsew", pady=60)

    def _clear_empty(self) -> None:
        if self._empty_label is not None:
            self._empty_label.destroy()
        self._empty_label = None
        self._empty_message = None

    def _discard_rows(self) -> None:
        for row in self._rows.values():
            row.destroy()
        self._rows.clear()
