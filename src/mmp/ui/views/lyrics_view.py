from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk

from ...arabic import display_text
from ...lyrics import LyricLine, LyricsData

if TYPE_CHECKING:
    from ...app import MagicMusicPlayerApp
    from ...models import Track


class LyricsView:
    """Real-time synchronized karaoke lyrics view."""

    def __init__(self, app: MagicMusicPlayerApp, parent: ctk.CTkFrame) -> None:
        self.app = app
        self.parent = parent
        self.current_track_id: str | None = None
        self.current_lyrics: LyricsData | None = None
        self.line_widgets: list[tuple[ctk.CTkButton, float]] = []
        self.active_line_index: int = -1
        self._loading_track_id: str | None = None
        self._view_state: str | None = None
        self._empty_message: str | None = None
        self._build_ui()

    def _build_ui(self) -> None:
        self.parent.grid_columnconfigure(0, weight=1)
        self.parent.grid_rowconfigure(1, weight=1)

        head = ctk.CTkFrame(self.parent, fg_color="transparent")
        head.grid(row=0, column=0, sticky="ew", padx=22, pady=(18, 6))

        title_label = ctk.CTkLabel(head, text="Lyrics", font=ctk.CTkFont(size=20, weight="bold"))
        title_label.pack(side="left")
        self.app._themed(title_label, text_color="text")

        self.track_info_label = ctk.CTkLabel(head, text="", font=ctk.CTkFont(size=12))
        self.app._themed(self.track_info_label, text_color="muted")
        self.track_info_label.pack(side="left", padx=(12, 0))

        self.lyrics_frame = ctk.CTkScrollableFrame(self.parent, fg_color=self.app.palette.bg)
        self.lyrics_frame.grid(row=1, column=0, sticky="nsew", padx=14, pady=(4, 10))
        self.app._themed(self.lyrics_frame, fg_color="bg")

    def render(self, force: bool = False) -> None:
        track = self.app.current_track
        if track is None:
            self.current_track_id = None
            self.current_lyrics = None
            self._loading_track_id = None
            self._show_empty("No song currently playing.\nPlay a song to view lyrics.")
            return

        if self.current_track_id == track.id and not force:
            if self._loading_track_id == track.id:
                return
            if self.current_lyrics is not None:
                return

        self.current_track_id = track.id
        self.current_lyrics = None
        self._loading_track_id = track.id
        clean_title = display_text(track.title)
        self.track_info_label.configure(text=f"{clean_title[:35]} \u00b7 {display_text(track.artist)[:25]}")
        self._show_loading()

        self.app.worker.submit(
            self.app.lyrics_service.get_lyrics(track),
            lambda future, tid=track.id: self.app.dispatch(lambda: self._on_lyrics_loaded(tid, future)),
        )

    def _show_empty(self, message: str) -> None:
        if self._view_state == "empty" and self._empty_message == message:
            return
        self.line_widgets.clear()
        self.active_line_index = -1
        self._clear_contents()
        ctk.CTkLabel(
            self.lyrics_frame,
            text=message,
            font=ctk.CTkFont(size=14),
            text_color=self.app.palette.muted,
            justify="center",
        ).pack(pady=80)
        self._view_state = "empty"
        self._empty_message = message

    def _show_loading(self) -> None:
        if self._view_state == "loading" and self._loading_track_id == self.current_track_id:
            return
        self.line_widgets.clear()
        self.active_line_index = -1
        self._clear_contents()
        ctk.CTkLabel(
            self.lyrics_frame,
            text="Searching synchronized lyrics...",
            font=ctk.CTkFont(size=13),
            text_color=self.app.palette.muted,
        ).pack(pady=80)
        self._view_state = "loading"
        self._empty_message = None

    def _clear_contents(self) -> None:
        for child in self.lyrics_frame.winfo_children():
            child.destroy()

    def _on_lyrics_loaded(self, track_id: str, future) -> None:
        if self.current_track_id != track_id:
            return
        self._loading_track_id = None
        try:
            lyrics: LyricsData = future.result()
        except Exception:
            lyrics = LyricsData(synced=[], plain=None)

        self.current_lyrics = lyrics
        self.line_widgets.clear()
        self.active_line_index = -1

        if not lyrics.has_lyrics:
            self._show_empty("No synchronized lyrics found for this track.")
            return

        self._clear_contents()
        self._empty_message = None

        # Render Synced Lyrics
        if lyrics.synced:
            # Top padding for smooth vertical centering
            spacer_top = ctk.CTkFrame(self.lyrics_frame, height=40, fg_color="transparent")
            spacer_top.pack(fill="x")

            for index, line in enumerate(lyrics.synced):
                text = line.text if line.text.strip() else "\u266B"
                btn = ctk.CTkButton(
                    self.lyrics_frame,
                    text=display_text(text),
                    anchor="center",
                    font=ctk.CTkFont(size=15),
                    fg_color="transparent",
                    hover_color=self.app.palette.hover,
                    text_color=self.app.palette.muted,
                    command=lambda ts=line.timestamp: self._on_line_click(ts),
                )
                btn.pack(fill="x", padx=20, pady=6)
                self.line_widgets.append((btn, line.timestamp))

            # Bottom padding
            spacer_bottom = ctk.CTkFrame(self.lyrics_frame, height=120, fg_color="transparent")
            spacer_bottom.pack(fill="x")
            self._view_state = "synced"
        elif lyrics.plain:
            # Plain unsynced lyrics fallback
            ctk.CTkLabel(
                self.lyrics_frame,
                text=display_text(lyrics.plain),
                font=ctk.CTkFont(size=14),
                text_color=self.app.palette.text,
                justify="center",
            ).pack(padx=20, pady=20)
            self._view_state = "plain"

    def _on_line_click(self, timestamp: float) -> None:
        self.app.player.seek_absolute(timestamp)

    def update_playback_position(self, position: float) -> None:
        """Called periodically by app to highlight and auto-scroll the active lyric line."""
        if not self.line_widgets or not self.current_lyrics or not self.current_lyrics.synced:
            return

        new_active = self.app.lyrics_service.find_active_line_index(self.current_lyrics.synced, position)
        if new_active == self.active_line_index:
            return

        # Dim previous line
        if 0 <= self.active_line_index < len(self.line_widgets):
            old_btn, _ = self.line_widgets[self.active_line_index]
            try:
                if old_btn.winfo_exists():
                    old_btn.configure(
                        font=ctk.CTkFont(size=15),
                        text_color=self.app.palette.muted,
                    )
            except Exception:
                pass

        # Highlight new active line
        self.active_line_index = new_active
        if 0 <= new_active < len(self.line_widgets):
            new_btn, _ = self.line_widgets[new_active]
            try:
                if new_btn.winfo_exists():
                    new_btn.configure(
                        font=ctk.CTkFont(size=18, weight="bold"),
                        text_color=self.app.palette.accent,
                    )
                    # Scroll canvas to keep active line centered
                    canvas = getattr(self.lyrics_frame, "_parent_canvas", None)
                    if canvas is not None:
                        total_lines = len(self.line_widgets)
                        fraction = max(0.0, min(1.0, (new_active - 2) / max(1, total_lines)))
                        canvas.yview_moveto(fraction)
            except Exception:
                pass
