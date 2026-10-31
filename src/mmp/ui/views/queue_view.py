from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk

from .list_renderer import RenderedTrack, TrackListRenderer
from ..components.player_bar import format_time

if TYPE_CHECKING:
    from ...app import MagicMusicPlayerApp


class QueueView:
    """Manages the Up Next playback queue interface."""

    def __init__(self, app: MagicMusicPlayerApp, parent: ctk.CTkFrame) -> None:
        self.app = app
        self.parent = parent
        self._dirty = True
        self._count_text: str = ""
        self._renderer: TrackListRenderer | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        self.parent.grid_columnconfigure(0, weight=1)
        self.parent.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(self.parent, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=22, pady=(18, 6))
        title_label = ctk.CTkLabel(head, text="Up Next", font=ctk.CTkFont(size=20, weight="bold"))
        title_label.pack(side="left")
        self.app._themed(title_label, text_color="text")

        self.queue_count_label = ctk.CTkLabel(head, text="", font=ctk.CTkFont(size=12))
        self.app._themed(self.queue_count_label, text_color="muted")
        self.queue_count_label.pack(side="left", padx=(12, 0))

        clear_btn = ctk.CTkButton(
            head,
            text="Clear Queue",
            width=104,
            height=32,
            corner_radius=16,
            command=self.app._clear_queue,
        )
        clear_btn.pack(side="right")
        self.app._themed(clear_btn, fg_color="idle", hover_color="idle_hover", text_color="text")

        self.export_btn = ctk.CTkButton(
            head,
            text="Save Queue",
            width=96,
            height=32,
            corner_radius=16,
            command=self.app._export_queue_playlist,
        )
        self.export_btn.pack(side="right", padx=(0, 8))
        self.app._themed(self.export_btn, fg_color="idle", hover_color="idle_hover", text_color="text")

        self.queue_frame = ctk.CTkScrollableFrame(self.parent, fg_color=self.app.palette.bg)
        self.queue_frame.grid(row=1, column=0, sticky="nsew", padx=14, pady=(4, 10))
        self.app._themed(self.queue_frame, fg_color="bg")
        self._renderer = TrackListRenderer(
            self.app,
            self.queue_frame,
            "queue",
            on_loading=self._set_loading_status,
        )

    def invalidate(self) -> None:
        self._dirty = True

    def render_if_dirty(self) -> None:
        if self._dirty:
            self.render()

    def render(self) -> None:
        self._dirty = False
        snapshot = self.app.queue.snapshot()
        total_tracks = len(snapshot.tracks)
        curr = snapshot.current_index + 1 if snapshot.current_index >= 0 else 0
        total_sec = sum(t.duration for t in snapshot.tracks if t.duration and t.duration > 0)
        dur_str = f" \u00b7 {format_time(total_sec)}" if total_sec > 0 else ""
        if total_tracks > 0:
            self._count_text = f"{curr}/{total_tracks} \u00b7 {total_tracks} tracks{dur_str}"
        else:
            self._count_text = "0 tracks"
        self.queue_count_label.configure(text=self._count_text)
        occurrences: dict[str, int] = {}
        items: list[RenderedTrack] = []
        for track in snapshot.tracks:
            occurrence = occurrences.get(track.id, 0)
            occurrences[track.id] = occurrence + 1
            items.append(RenderedTrack((track.id, occurrence), track))
        if self._renderer is not None:
            self._renderer.render(items, "Queue is empty.\nAdd tracks with the + button on any result.")

    def _set_loading_status(self, loading: bool) -> None:
        text = self._count_text + (" · Updating…" if loading else "")
        if self.queue_count_label.cget("text") != text:
            self.queue_count_label.configure(text=text)
