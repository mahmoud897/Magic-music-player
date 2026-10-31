from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import customtkinter as ctk

from ...models import Track
from .list_renderer import RenderedTrack, TrackListRenderer

if TYPE_CHECKING:
    from ...app import MagicMusicPlayerApp

AUDIO_EXTENSIONS = {".mp3", ".m4a", ".opus", ".flac", ".wav"}


class DownloadsView:
    """Manages the offline downloaded files view and active download statuses."""

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
        title_label = ctk.CTkLabel(head, text="Downloads", font=ctk.CTkFont(size=20, weight="bold"))
        title_label.pack(side="left")
        self.app._themed(title_label, text_color="text")

        self.downloads_count_label = ctk.CTkLabel(head, text="", font=ctk.CTkFont(size=12))
        self.app._themed(self.downloads_count_label, text_color="muted")
        self.downloads_count_label.pack(side="left", padx=(12, 0))

        refresh_btn = ctk.CTkButton(
            head,
            text="Refresh",
            width=72,
            height=32,
            corner_radius=16,
            command=self.refresh,
        )
        refresh_btn.pack(side="right", padx=(8, 0))
        self.app._themed(refresh_btn, fg_color="idle", hover_color="idle_hover", text_color="text")

        open_btn = ctk.CTkButton(
            head,
            text="Open Folder" if not self.app.icons.available() else "  " + self.app.icons.glyph("folder") + "  ",
            width=44 if self.app.icons.available() else 110,
            height=32,
            corner_radius=16,
            font=self.app.icons.font(13) if self.app.icons.available() else ctk.CTkFont(size=12),
            command=self.app._open_downloads_folder,
        )
        open_btn.pack(side="right", padx=(8, 0))
        self.app._themed(open_btn, fg_color="idle", hover_color="idle_hover", text_color="text")

        self.filter_entry = ctk.CTkEntry(
            head,
            placeholder_text="Filter downloads...",
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
        self.filter_entry.pack(side="right")
        self.filter_entry.bind("<KeyRelease>", lambda _e: self.render())

        self.downloads_frame = ctk.CTkScrollableFrame(self.parent, fg_color=self.app.palette.bg)
        self.downloads_frame.grid(row=1, column=0, sticky="nsew", padx=14, pady=(4, 10))
        self.app._themed(self.downloads_frame, fg_color="bg")
        self._renderer = TrackListRenderer(
            self.app,
            self.downloads_frame,
            "downloads",
            on_loading=self._set_loading_status,
        )

    def invalidate(self) -> None:
        self._dirty = True

    def refresh(self) -> None:
        self.invalidate()
        self.render()

    def render_if_dirty(self) -> None:
        if self._dirty:
            self.render()

    def _list_downloaded_files(self) -> list[Path]:
        directory = self.app.config_model.ensure_download_dir()
        try:
            return [p for p in directory.iterdir() if p.suffix.lower() in AUDIO_EXTENSIONS]
        except OSError:
            return []

    def render(self) -> None:
        self._dirty = False
        files_with_stats = []
        for path in self._list_downloaded_files():
            try:
                files_with_stats.append((path, path.stat()))
            except OSError:
                continue
        files_with_stats.sort(key=lambda item: item[1].st_mtime, reverse=True)
        query = self.filter_entry.get().strip().casefold() if hasattr(self, "filter_entry") else ""
        if query:
            files_with_stats = [
                item for item in files_with_stats
                if query in item[0].stem.casefold()
            ]

        total_mb = sum(stat.st_size for _path, stat in files_with_stats) / (1024 * 1024)
        self._count_text = f"{len(files_with_stats)} tracks \u00b7 {total_mb:.0f} MB"
        self.downloads_count_label.configure(text=self._count_text)
        items: list[RenderedTrack] = []
        for path, stat in files_with_stats:
            size_mb = stat.st_size / (1024 * 1024)
            fake_track = Track(
                id=f"local:{path.name}",
                title=path.stem,
                artist="",
                duration=None,
                source="Local",
                webpage_url=str(path),
                thumbnail_url=None,
            )
            items.append(
                RenderedTrack(
                    key=str(path),
                    track=fake_track,
                    trailing=f"{size_mb:.1f} MB  \u00b7  {path.suffix.lstrip('.').upper()}",
                )
            )
        if self._renderer is not None:
            empty = (
                f"No downloaded files matching '{self.filter_entry.get().strip()}'"
                if query
                else "No downloaded music yet.\nHit the \u2193 button on a search result."
            )
            try:
                self._renderer.render(items, empty, scroll_key=f"downloads:{query}")
            except TypeError:
                self._renderer.render(items, empty)

    def _set_loading_status(self, loading: bool) -> None:
        text = self._count_text + (" · Updating…" if loading else "")
        if self.downloads_count_label.cget("text") != text:
            self.downloads_count_label.configure(text=text)
