from __future__ import annotations

import tkinter as tk
from typing import TYPE_CHECKING

import customtkinter as ctk

from ...arabic import display_text
from ...player import PlaybackState

if TYPE_CHECKING:
    from ...app import MagicMusicPlayerApp
    from ...models import Track


def format_time(seconds: float) -> str:
    minutes, seconds = divmod(int(max(0, seconds)), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def table_text(text: str, max_chars: int) -> str:
    clean = " ".join(text.split())
    if len(clean) > max_chars:
        clean = f"{clean[: max_chars - 3]}..."
    return display_text(clean)


class PlayerBarComponent:
    """Encapsulates the bottom player control bar."""

    def __init__(self, app: MagicMusicPlayerApp, parent: ctk.CTkBaseClass) -> None:
        self.app = app
        self.parent = parent
        self.seeking = False
        self._muted = False
        self._pre_mute_volume = 70

        self._build_ui()

    def _build_ui(self) -> None:
        self.frame = self.app._themed(
            ctk.CTkFrame(self.parent, corner_radius=0, height=100),
            fg_color="surface",
        )
        self.frame.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.frame.grid_columnconfigure(0, weight=3, uniform="pb")
        self.frame.grid_columnconfigure(1, weight=4, uniform="pb")
        self.frame.grid_columnconfigure(2, weight=3, uniform="pb")

        # ----------------- Left: Art & Track Info -----------------
        left = ctk.CTkFrame(self.frame, fg_color="transparent")
        left.grid(row=0, column=0, sticky="ew", padx=(16, 8), pady=(10, 4))

        self.art_label = ctk.CTkLabel(
            left,
            text=self.app.icons.glyph("music_note") if self.app.icons.available() else "\u266B",
            font=self.app.icons.font(20),
            width=48,
            height=48,
            corner_radius=8,
        )
        self.app._themed(self.art_label, fg_color="surface_alt", text_color="muted")
        self.art_label.pack(side="left", padx=(0, 12))

        info = ctk.CTkFrame(left, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)

        self.track_title_label = ctk.CTkLabel(
            info,
            text="Nothing playing",
            anchor="w",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.app._themed(self.track_title_label, text_color="text")
        self.track_title_label.pack(fill="x")

        self.track_artist_label = ctk.CTkLabel(
            info,
            text="Search to get started",
            anchor="w",
            font=ctk.CTkFont(size=11),
        )
        self.app._themed(self.track_artist_label, text_color="muted")
        self.track_artist_label.pack(fill="x")

        # ----------------- Center: Transport & Progress -----------------
        center = ctk.CTkFrame(self.frame, fg_color="transparent")
        center.grid(row=0, column=1, sticky="ew", pady=(10, 4))
        center.grid_columnconfigure(0, weight=1)

        transport = ctk.CTkFrame(center, fg_color="transparent")
        transport.grid(row=0, column=0)
        small_icon_font = self.app.icons.font(14) if self.app.icons.available() else ctk.CTkFont(size=12)

        self.shuffle_button = ctk.CTkButton(
            transport,
            text=self.app._glyph_or("shuffle"),
            width=36,
            height=34,
            corner_radius=17,
            fg_color=self.app.palette.idle,
            hover_color=self.app.palette.idle_hover,
            text_color=self.app.palette.text,
            font=small_icon_font,
            command=self.app._toggle_shuffle,
        )
        self.shuffle_button.grid(row=0, column=0, padx=4)
        self.app._themed(self.shuffle_button, fg_color="idle", hover_color="idle_hover", text_color="text")

        self.prev_button = ctk.CTkButton(
            transport,
            text=self.app._glyph_or("prev"),
            width=40,
            height=38,
            corner_radius=19,
            fg_color=self.app.palette.idle,
            hover_color=self.app.palette.idle_hover,
            text_color=self.app.palette.text,
            font=small_icon_font,
            command=self.app._prev_track,
        )
        self.prev_button.grid(row=0, column=1, padx=4)
        self.app._themed(self.prev_button, fg_color="idle", hover_color="idle_hover", text_color="text")

        self.play_button = ctk.CTkButton(
            transport,
            text=self.app._glyph_or("play"),
            width=52,
            height=52,
            corner_radius=26,
            fg_color=self.app.palette.accent,
            hover_color=self.app.palette.accent_hover,
            text_color="#ffffff",
            font=self.app.icons.font(20) if self.app.icons.available() else ctk.CTkFont(size=18),
            command=self.app._toggle_pause,
        )
        self.play_button.grid(row=0, column=2, padx=6)
        self.app._themed(self.play_button, fg_color="accent", hover_color="accent_hover")

        self.next_button = ctk.CTkButton(
            transport,
            text=self.app._glyph_or("next"),
            width=40,
            height=38,
            corner_radius=19,
            fg_color=self.app.palette.idle,
            hover_color=self.app.palette.idle_hover,
            text_color=self.app.palette.text,
            font=small_icon_font,
            command=self.app._next_track,
        )
        self.next_button.grid(row=0, column=3, padx=4)
        self.app._themed(self.next_button, fg_color="idle", hover_color="idle_hover", text_color="text")

        self.repeat_button = ctk.CTkButton(
            transport,
            text=self.app._glyph_or("repeat_all"),
            width=36,
            height=34,
            corner_radius=17,
            fg_color=self.app.palette.idle,
            hover_color=self.app.palette.idle_hover,
            text_color=self.app.palette.text,
            font=small_icon_font,
            command=self.app._cycle_repeat,
        )
        self.repeat_button.grid(row=0, column=4, padx=4)
        self.app._themed(self.repeat_button, fg_color="idle", hover_color="idle_hover", text_color="text")

        # Seek row
        seek_row = ctk.CTkFrame(center, fg_color="transparent")
        seek_row.grid(row=1, column=0, sticky="ew", pady=(4, 0), padx=6)
        seek_row.grid_columnconfigure(1, weight=1)

        self.position_label = ctk.CTkLabel(seek_row, text="0:00", width=42, font=ctk.CTkFont(size=10))
        self.app._themed(self.position_label, text_color="muted")
        self.position_label.grid(row=0, column=0)

        self.seek_slider = ctk.CTkSlider(
            seek_row,
            from_=0,
            to=1,
            height=16,
            command=self._on_seek_drag,
            progress_color=self.app.palette.accent,
            button_color=self.app.palette.accent,
            button_hover_color=self.app.palette.accent_hover,
        )
        self.seek_slider.set(0)
        self.seek_slider.grid(row=0, column=1, sticky="ew", padx=6)
        self.seek_slider.bind("<ButtonPress-1>", lambda _event: setattr(self, "seeking", True))
        self.seek_slider.bind("<ButtonRelease-1>", self._on_seek_release)
        self.app._themed(
            self.seek_slider,
            progress_color="accent",
            button_color="accent",
            button_hover_color="accent_hover",
        )

        self.duration_label = ctk.CTkLabel(seek_row, text="0:00", width=42, font=ctk.CTkFont(size=10))
        self.app._themed(self.duration_label, text_color="muted")
        self.duration_label.grid(row=0, column=2)

        # ----------------- Right: Heart, Download & Volume -----------------
        right = ctk.CTkFrame(self.frame, fg_color="transparent")
        right.grid(row=0, column=2, sticky="e", padx=(8, 16), pady=(10, 4))

        self.heart_button = ctk.CTkButton(
            right,
            text=self.app._glyph_or("heart"),
            width=32,
            height=32,
            corner_radius=8,
            fg_color="transparent",
            hover_color=self.app.palette.hover,
            text_color=self.app.palette.muted,
            font=self.app.icons.font(15) if self.app.icons.available() else ctk.CTkFont(size=13),
            state="disabled",
            command=self.app._toggle_heart_current,
        )
        self.heart_button.pack(side="left", padx=2)
        self.app._themed(self.heart_button, hover_color="hover")

        self.download_button = ctk.CTkButton(
            right,
            text=self.app._glyph_or("download"),
            width=32,
            height=32,
            corner_radius=8,
            fg_color="transparent",
            hover_color=self.app.palette.hover,
            text_color=self.app.palette.muted,
            font=self.app.icons.font(15) if self.app.icons.available() else ctk.CTkFont(size=13),
            state="disabled",
            command=self.app._download_current,
        )
        self.download_button.pack(side="left", padx=2)
        self.app._themed(self.download_button, hover_color="hover", text_color="muted")

        self.lyrics_button = ctk.CTkButton(
            right,
            text=self.app.icons.glyph("music_note") if self.app.icons.available() else "\u266B",
            width=32,
            height=32,
            corner_radius=8,
            fg_color="transparent",
            hover_color=self.app.palette.hover,
            text_color=self.app.palette.muted,
            font=self.app.icons.font(14) if self.app.icons.available() else ctk.CTkFont(size=12),
            command=self.app._toggle_lyrics_view,
        )
        self.lyrics_button.pack(side="left", padx=2)
        self.app._themed(self.lyrics_button, hover_color="hover", text_color="muted")

        self.radio_button = ctk.CTkButton(
            right,
            text=self.app._glyph_or("radio"),
            width=32,
            height=32,
            corner_radius=8,
            fg_color="transparent",
            hover_color=self.app.palette.hover,
            text_color=self.app.palette.muted,
            font=self.app.icons.font(14) if self.app.icons.available() else ctk.CTkFont(size=12),
            command=self.app._toggle_auto_radio,
        )
        self.radio_button.pack(side="left", padx=2)
        self.app._themed(self.radio_button, hover_color="hover")

        self.sleep_timer_button = ctk.CTkButton(
            right,
            text=self.app.icons.glyph("timer") if self.app.icons.available() else self.app._glyph_or("timer"),
            width=32,
            height=32,
            corner_radius=8,
            fg_color="transparent",
            hover_color=self.app.palette.hover,
            text_color=self.app.palette.muted,
            font=self.app.icons.font(14) if self.app.icons.available() else ctk.CTkFont(size=12),
            command=self._on_sleep_timer_clicked,
        )
        self.sleep_timer_button.pack(side="left", padx=2)
        self.app._themed(self.sleep_timer_button, hover_color="hover")

        volume_wrap = ctk.CTkFrame(right, fg_color="transparent")
        volume_wrap.pack(side="left", padx=(10, 0))

        # Dynamic volume icon button with click-to-mute
        self.vol_button = ctk.CTkButton(
            volume_wrap,
            text=self._get_volume_glyph(70, False),
            width=28,
            height=28,
            corner_radius=6,
            fg_color="transparent",
            hover_color=self.app.palette.hover,
            text_color=self.app.palette.muted,
            font=self.app.icons.font(14) if self.app.icons.available() else ctk.CTkFont(size=12),
            command=self._toggle_mute,
        )
        self.app._themed(self.vol_button, hover_color="hover", text_color="muted")
        self.vol_button.pack(side="left", padx=(0, 2))

        self.volume_slider = ctk.CTkSlider(
            volume_wrap,
            from_=0,
            to=100,
            width=100,
            height=16,
            command=self._on_volume_slide,
            progress_color=self.app.palette.accent,
            button_color=self.app.palette.accent,
            button_hover_color=self.app.palette.accent_hover,
        )
        self.volume_slider.set(70)
        self.volume_slider.pack(side="left")
        self.volume_slider.bind("<ButtonRelease-1>", lambda _event: self.app._persist_volume())
        self.app._themed(
            self.volume_slider,
            progress_color="accent",
            button_color="accent",
            button_hover_color="accent_hover",
        )

        # Progress bar for active downloads/processing
        self.download_progress = ctk.CTkProgressBar(
            self.frame,
            height=3,
            corner_radius=0,
            progress_color=self.app.palette.accent,
        )
        self.download_progress.set(0)
        self.download_progress.grid(row=1, column=0, columnspan=3, sticky="ews", padx=0, pady=0)
        self.app._themed(self.download_progress, progress_color="accent")

    def _get_volume_glyph(self, volume: int, muted: bool) -> str:
        if muted or volume == 0:
            return self.app._glyph_or("volume_mute")
        return self.app._glyph_or("volume")

    def update_volume_ui(self, volume: int, muted: bool) -> None:
        self._muted = muted
        self.vol_button.configure(
            text=self._get_volume_glyph(volume, muted),
            text_color=self.app.palette.accent if (muted or volume == 0) else self.app.palette.muted,
        )

    def update_radio_ui(self, enabled: bool) -> None:
        self.radio_button.configure(
            fg_color=self.app.palette.accent if enabled else "transparent",
            hover_color=self.app.palette.accent_hover if enabled else self.app.palette.hover,
            text_color="#ffffff" if enabled else self.app.palette.muted,
        )

    def _toggle_mute(self) -> None:
        self.app._hotkey_mute()

    def _on_volume_slide(self, value: float) -> None:
        vol = int(value)
        if vol > 0:
            self._muted = False
        self.update_volume_ui(vol, self._muted)
        self.app._set_volume(vol)

    def _on_seek_drag(self, value: float) -> None:
        if self.seeking:
            self.position_label.configure(text=format_time(value))

    def _on_seek_release(self, _event: object) -> None:
        self.seeking = False
        self.app.player.seek_absolute(float(self.seek_slider.get()))

    def update_playback_state(self, state: PlaybackState | None) -> None:
        if state is None:
            return
        try:
            raw_duration = float(getattr(state, "duration", 0.0) or 0.0)
            raw_position = float(getattr(state, "position", 0.0) or 0.0)
        except (TypeError, ValueError):
            return
        duration = max(1.0, raw_duration)
        if getattr(self, "_last_duration", None) != duration:
            self.seek_slider.configure(to=duration)
            self._last_duration = duration

        if not self.seeking:
            self.seek_slider.set(min(raw_position, duration))
            pos_text = format_time(raw_position)
            if getattr(self, "_last_pos_text", None) != pos_text:
                self.position_label.configure(text=pos_text)
                self._last_pos_text = pos_text

        dur_text = format_time(raw_duration)
        if getattr(self, "_last_dur_text", None) != dur_text:
            self.duration_label.configure(text=dur_text)
            self._last_dur_text = dur_text

        if self.play_button.cget("state") == "normal":
            glyph = "pause" if not getattr(state, "paused", True) else "play"
            desired = self.app._glyph_or(glyph)
            if self.play_button.cget("text") != desired:
                self.play_button.configure(text=desired)

    def set_track_info(self, track: Track | None, status_prefix: str = "") -> None:
        if track is None:
            self.track_title_label.configure(text="Nothing playing")
            self.track_artist_label.configure(text="Search to get started")
            self.download_button.configure(state="disabled")
            self.heart_button.configure(state="disabled", text=self.app._glyph_or("heart"))
            self.set_art_thumbnail(None)
            return

        if status_prefix:
            self.track_title_label.configure(text=f"{status_prefix} {table_text(track.title, 34)}")
        else:
            self.track_title_label.configure(text=table_text(track.title, 36))
        self.track_artist_label.configure(text=table_text(track.artist, 28))
        self.download_button.configure(state="normal")
        self.set_art_thumbnail(track)

    def set_art_thumbnail(self, track: Track | None) -> None:
        glyph = self.app.icons.glyph("music_note") if self.app.icons.available() else "\u266B"
        if track is None or not track.thumbnail_url:
            try:
                self.art_label.configure(image=None, text=glyph)
            except Exception:
                pass
            return
        self.app._request_art(track, self.art_label, 48)

    def _on_sleep_timer_clicked(self) -> tk.Menu:
        if getattr(self, "_sleep_timer_menu", None) is not None:
            try:
                self._sleep_timer_menu.destroy()
            except Exception:
                pass
        menu = tk.Menu(
            self.app,
            tearoff=0,
            bg=self.app.palette.surface,
            fg=self.app.palette.text,
            activebackground=self.app.palette.accent,
            activeforeground="#ffffff",
            relief="flat",
            bd=1,
        )
        self._sleep_timer_menu = menu
        if self.app.is_sleep_timer_active():
            menu.add_command(label="Turn Off Sleep Timer", command=lambda: self.app.cancel_sleep_timer(toast=True))
            menu.add_separator()
        menu.add_command(label="15 Minutes", command=lambda: self.app.set_sleep_timer(15))
        menu.add_command(label="30 Minutes", command=lambda: self.app.set_sleep_timer(30))
        menu.add_command(label="45 Minutes", command=lambda: self.app.set_sleep_timer(45))
        menu.add_command(label="60 Minutes", command=lambda: self.app.set_sleep_timer(60))
        menu.add_separator()
        menu.add_command(label="End of Current Track", command=lambda: self.app.set_sleep_timer(end_of_track=True))

        try:
            x = self.sleep_timer_button.winfo_rootx()
            y = self.sleep_timer_button.winfo_rooty() - 170
            menu.post(x, max(0, y))
        except Exception:
            pass
        return menu

    def update_sleep_timer_ui(self, active: bool) -> None:
        color = self.app.palette.accent if active else self.app.palette.muted
        self.sleep_timer_button.configure(text_color=color)
