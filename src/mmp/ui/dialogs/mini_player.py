from __future__ import annotations

from typing import TYPE_CHECKING

import customtkinter as ctk

from ...arabic import display_text
from ...player import PlaybackState

if TYPE_CHECKING:
    from ...app import MagicMusicPlayerApp
    from ...models import Track


class MiniPlayerWindow(ctk.CTkToplevel):
    """Compact, always-on-top floating desktop widget with media transport controls."""

    def __init__(self, app: MagicMusicPlayerApp) -> None:
        super().__init__(app)
        self.app = app
        self.title("MMP Mini Player")
        self.geometry("360x110")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.configure(fg_color=app.palette.surface)

        # Dragging mechanics for floating window
        self._drag_start_x = 0
        self._drag_start_y = 0

        self._build_ui()
        self._sync_state()
        self.protocol("WM_DELETE_WINDOW", self.restore_main)

    def _build_ui(self) -> None:
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=12, pady=10)
        main.grid_columnconfigure(1, weight=1)

        # Enable dragging from background frame
        main.bind("<Button-1>", self._start_drag)
        main.bind("<B1-Motion>", self._on_drag)

        # Album Art
        self.art_label = ctk.CTkLabel(
            main,
            text=self.app.icons.glyph("music_note") if self.app.icons.available() else "\u266B",
            font=self.app.icons.font(18),
            width=46,
            height=46,
            corner_radius=8,
            fg_color=self.app.palette.surface_alt,
            text_color=self.app.palette.muted,
        )
        self.art_label.grid(row=0, column=0, rowspan=2, padx=(0, 10), sticky="w")
        self.art_label.bind("<Button-1>", self._start_drag)
        self.art_label.bind("<B1-Motion>", self._on_drag)

        # Info Header
        info = ctk.CTkFrame(main, fg_color="transparent")
        info.grid(row=0, column=1, sticky="ew")
        info.grid_columnconfigure(0, weight=1)

        self.title_label = ctk.CTkLabel(
            info,
            text="Nothing playing",
            font=ctk.CTkFont(size=12, weight="bold"),
            anchor="w",
            text_color=self.app.palette.text,
        )
        self.title_label.grid(row=0, column=0, sticky="ew")

        self.artist_label = ctk.CTkLabel(
            info,
            text="MMP Floating Player",
            font=ctk.CTkFont(size=10),
            anchor="w",
            text_color=self.app.palette.muted,
        )
        self.artist_label.grid(row=1, column=0, sticky="ew")

        # Restore / Close mini button
        restore_btn = ctk.CTkButton(
            info,
            text="\u2922",
            width=24,
            height=24,
            corner_radius=6,
            fg_color="transparent",
            hover_color=self.app.palette.hover,
            text_color=self.app.palette.muted,
            command=self.restore_main,
        )
        restore_btn.grid(row=0, column=1, rowspan=2, padx=(4, 0), sticky="ne")

        # Controls & Progress
        bottom = ctk.CTkFrame(main, fg_color="transparent")
        bottom.grid(row=1, column=1, sticky="ew", pady=(4, 0))
        bottom.grid_columnconfigure(3, weight=1)

        self.prev_btn = ctk.CTkButton(
            bottom,
            text=self.app._glyph_or("prev"),
            width=28,
            height=26,
            corner_radius=6,
            fg_color="transparent",
            hover_color=self.app.palette.hover,
            text_color=self.app.palette.text,
            command=self.app._prev_track,
        )
        self.prev_btn.grid(row=0, column=0, padx=2)

        self.play_btn = ctk.CTkButton(
            bottom,
            text=self.app._glyph_or("play"),
            width=32,
            height=26,
            corner_radius=13,
            fg_color=self.app.palette.accent,
            hover_color=self.app.palette.accent_hover,
            text_color="#ffffff",
            command=self.app._toggle_pause,
        )
        self.play_btn.grid(row=0, column=1, padx=2)

        self.next_btn = ctk.CTkButton(
            bottom,
            text=self.app._glyph_or("next"),
            width=28,
            height=26,
            corner_radius=6,
            fg_color="transparent",
            hover_color=self.app.palette.hover,
            text_color=self.app.palette.text,
            command=self.app._next_track,
        )
        self.next_btn.grid(row=0, column=2, padx=2)

        self.progress = ctk.CTkProgressBar(
            bottom,
            height=4,
            corner_radius=2,
            progress_color=self.app.palette.accent,
        )
        self.progress.set(0)
        self.progress.grid(row=0, column=3, padx=(8, 0), sticky="ew")

    def _start_drag(self, event: object) -> None:
        self._drag_start_x = getattr(event, "x", 0)
        self._drag_start_y = getattr(event, "y", 0)

    def _on_drag(self, event: object) -> None:
        cur_x = getattr(event, "x", 0)
        cur_y = getattr(event, "y", 0)
        delta_x = cur_x - self._drag_start_x
        delta_y = cur_y - self._drag_start_y
        new_x = self.winfo_x() + delta_x
        new_y = self.winfo_y() + delta_y
        self.geometry(f"+{new_x}+{new_y}")

    def update_playback(self, state: PlaybackState | None, track: Track | None) -> None:
        if track is not None:
            self.title_label.configure(text=display_text(track.title[:30]))
            self.artist_label.configure(text=display_text(track.artist[:24]))
            if track.thumbnail_url:
                self.app._request_art(track, self.art_label, 46)
        else:
            self.title_label.configure(text="Nothing playing")
            self.artist_label.configure(text="MMP Floating Player")

        if state is not None:
            glyph = "pause" if not getattr(state, "paused", True) else "play"
            self.play_btn.configure(text=self.app._glyph_or(glyph))
            try:
                duration = float(getattr(state, "duration", 0.0) or 0.0)
                position = float(getattr(state, "position", 0.0) or 0.0)
                if duration > 0:
                    self.progress.set(max(0.0, min(1.0, position / duration)))
            except (TypeError, ValueError):
                pass

    def _sync_state(self) -> None:
        try:
            state = self.app.player.state()
        except Exception:
            state = None
        self.update_playback(state, self.app.current_track)
        if self.winfo_exists():
            self.after(500, self._sync_state)

    def restore_main(self) -> None:
        self.app.deiconify()
        self.app.lift()
        self.destroy()
