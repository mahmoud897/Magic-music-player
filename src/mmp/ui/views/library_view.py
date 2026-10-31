from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk

from .list_renderer import RenderedTrack, TrackListRenderer

if TYPE_CHECKING:
    from ...app import MagicMusicPlayerApp


class LibraryView:
    """Manages the Favorites and Recently Played lists."""

    def __init__(self, app: MagicMusicPlayerApp, parent: ctk.CTkFrame) -> None:
        self.app = app
        self.parent = parent
        self._dirty = True
        self._renderer: TrackListRenderer | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        self.parent.grid_columnconfigure(0, weight=1)
        self.parent.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(self.parent, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=22, pady=(18, 6))
        title_label = ctk.CTkLabel(head, text="Your Library", font=ctk.CTkFont(size=20, weight="bold"))
        title_label.pack(side="left")
        self.app._themed(title_label, text_color="text")

        self.library_segment = ctk.CTkSegmentedButton(
            head,
            values=["Favorites", "Recently Played"],
            command=self._on_mode_changed,
            selected_color=self.app.palette.accent,
            selected_hover_color=self.app.palette.accent_hover,
            unselected_color=self.app.palette.idle,
            unselected_hover_color=self.app.palette.idle_hover,
            text_color=self.app.palette.text,
        )
        self.app._themed(
            self.library_segment,
            selected_color="accent",
            selected_hover_color="accent_hover",
            unselected_color="idle",
            unselected_hover_color="idle_hover",
            text_color="text",
        )
        self.library_segment.set("Favorites")
        self.library_segment.pack(side="right")

        self.filter_entry = ctk.CTkEntry(
            head,
            placeholder_text="Filter library...",
            width=170,
            height=30,
            corner_radius=15,
            fg_color=self.app.palette.surface_alt,
            text_color=self.app.palette.text,
            border_color=self.app.palette.idle,
        )
        self.app._themed(
            self.filter_entry,
            fg_color="surface_alt",
            text_color="text",
            border_color="idle",
        )
        self.filter_entry.pack(side="right", padx=(0, 12))
        self.filter_entry.bind("<KeyRelease>", lambda _e: self.render())

        self.library_status_label = ctk.CTkLabel(head, text="", font=ctk.CTkFont(size=11))
        self.app._themed(self.library_status_label, text_color="muted")
        self.library_status_label.pack(side="right", padx=(0, 10))

        self.library_frame = ctk.CTkScrollableFrame(self.parent, fg_color=self.app.palette.bg)
        self.library_frame.grid(row=1, column=0, sticky="nsew", padx=14, pady=(4, 10))
        self.app._themed(self.library_frame, fg_color="bg")
        self._renderer = TrackListRenderer(
            self.app,
            self.library_frame,
            "library",
            on_loading=self._set_loading_status,
        )

    def _on_mode_changed(self, _value: str) -> None:
        self.invalidate()
        self.render_if_dirty()

    def invalidate(self) -> None:
        self._dirty = True

    def refresh(self) -> None:
        self.invalidate()
        self.render()

    def render_if_dirty(self) -> None:
        if self._dirty:
            self.render()

    def render(self) -> None:
        self._dirty = False
        mode = self.library_segment.get()
        if mode == "Favorites":
            tracks = self.app.library.favorites()
            empty = "No favorites yet.\nTap the \u2661 on any search result."
        else:
            tracks = self.app.library.recent_plays(limit=50)
            empty = "Nothing played yet.\nTracks you play will show up here."

        query = self.filter_entry.get().strip().casefold() if hasattr(self, "filter_entry") else ""
        if query:
            tracks = [
                t for t in tracks
                if query in t.title.casefold() or query in t.artist.casefold()
            ]
            if not tracks:
                empty = f"No tracks matching '{self.filter_entry.get().strip()}'"

        if self._renderer is not None:
            try:
                self._renderer.render(
                    [RenderedTrack(track.id, track) for track in tracks],
                    empty,
                    scroll_key=f"{mode}:{query}",
                )
            except TypeError:
                self._renderer.render(
                    [RenderedTrack(track.id, track) for track in tracks],
                    empty,
                )

    def _set_loading_status(self, loading: bool) -> None:
        text = "Updating…" if loading else ""
        if self.library_status_label.cget("text") != text:
            self.library_status_label.configure(text=text)
