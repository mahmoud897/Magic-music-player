from __future__ import annotations

import json
import queue
import sys
import time
import tkinter as tk
import weakref
from concurrent.futures import Future
from pathlib import Path
from tkinter import messagebox

import customtkinter as ctk

from . import __version__
from .arabic import display_text
from .async_bridge import AsyncWorker
from .cache_manager import AudioCacheManager
from .config import APP_DIR, PROJECT_ROOT, AppConfig, get_app_dir
from .downloader import DownloadManager, DownloadProgress, DownloadService, DownloadStatus, DownloadTask
from .library import MusicLibrary
from .logging_config import get_logger, setup_logging
from .models import Track
from .player import EQ_PRESETS, AudioPlayer, normalize_eq_gains
from .prefetch import PrefetchManager
from .queue_manager import PlaybackQueue, RepeatMode
from .search import ProviderSearchStatus, SearchService, StreamExtractor
from .theme import (
    ACCENT_DEFS,
    IconSheet,
    Palette,
    apply_appearance,
    build_palette,
    default_accent,
)
from .lyrics import LyricsService
from .thumbnails import ThumbnailService
from .ui.components.player_bar import PlayerBarComponent
from .ui.components.track_row import TrackRow
from .ui.dialogs.mini_player import MiniPlayerWindow
from .ui.dialogs.settings_dialog import SettingsDialog
from .ui.views.downloads_view import DownloadsView
from .ui.views.library_view import LibraryView
from .ui.views.lyrics_view import LyricsView
from .ui.views.queue_view import QueueView
from .ui.views.search_view import SearchView

logger = get_logger("app")

PAGES = ("search", "library", "downloads", "upnext", "lyrics")


def is_probably_arabic(text: str) -> bool:
    return any("\u0600" <= char <= "\u06ff" for char in text)


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


class MagicMusicPlayerApp(ctk.CTk):
    def __init__(self) -> None:
        super().__init__()

        self.title(f"Magic Music Player v{__version__}")
        self.geometry("1080x700")
        self.minsize(980, 620)

        # Load window icon if present
        icon_path = PROJECT_ROOT / "assets" / "icon.ico"
        if not icon_path.exists() and hasattr(sys, "_MEIPASS"):
            icon_path = Path(sys._MEIPASS) / "assets" / "icon.ico"
        if icon_path.exists():
            try:
                self.iconbitmap(str(icon_path))
            except Exception:
                pass

        # Core models and services
        self._ui_queue: queue.Queue[Callable[[], None]] = queue.Queue()
        self._poll_after_id: str | None = None
        self._refresh_after_id: str | None = None
        self._poll_ui_queue()
        self.config_model = AppConfig.load()
        self.config_model.ensure_download_dir()
        self.library = MusicLibrary(get_app_dir() / "library.db")
        self.recent_searches = self._load_recent_searches()
        self.cache_manager = AudioCacheManager(get_app_dir() / "cache")
        self.worker = AsyncWorker()
        self.search_service = SearchService()
        self.stream_extractor = StreamExtractor()

        self.player = AudioPlayer(
            on_track_end=lambda: self.dispatch(self._on_track_finished),
            on_track_error=lambda err: self.dispatch(lambda: self._on_track_playback_error(err)),
        )
        self.queue = PlaybackQueue()
        self.prefetch_manager = PrefetchManager(
            self.queue, self.stream_extractor, self.worker, self.cache_manager
        )
        self.lyrics_service = LyricsService()
        self.auto_radio_enabled = self.library.get_setting("auto_radio", "1") == "1"

        self.download_manager = DownloadManager(
            service_factory=lambda: DownloadService(
                self.config_model.ensure_download_dir(),
                self.config_model.audio_format,
                self.config_model.audio_quality_kbps,
                cache_manager=self.cache_manager,
            ),
            worker=self.worker,
            max_concurrent=2,
        )
        self.download_manager.add_listener(
            lambda task: self.dispatch(lambda: self._on_download_task_update(task))
        )

        self.icons = IconSheet()
        self.thumbnails = ThumbnailService(get_app_dir() / "thumbs")
        self._art_cache: dict[str, object] = {}
        self._art_labels: dict[str, list[tuple[ctk.CTkLabel, int]]] = {}

        self.current_track: Track | None = None
        self.current_stream_url: str | None = None
        self._current_track_retried: bool = False
        self.search_future: Future | None = None
        self._search_generation = 0
        self._search_using_cache_generation: int | None = None
        self.last_results: list[Track] = []
        self._search_results_dirty = False
        self._search_results_pending = False
        self._search_message: str | None = None
        self._last_searched_query: str | None = None
        self._search_partial_snapshot: tuple[list[Track], int] | None = None
        self._search_partial_after_id: str | None = None
        self._muted = False
        self._pre_mute_volume = 70
        self.play_generation = 0
        self._toast_after: str | None = None
        self._sleep_timer_after_id: str | None = None
        self._sleep_timer_end_of_track: bool = False
        self._sleep_timer_end_time: float | None = None
        self._sleep_timer_minutes: int | None = None
        self._pending_restore_position: float | None = None
        self._active_track_menu: tk.Menu | None = None
        self._themers: list = []
        self._nav_items: dict[str, dict] = {}
        self.active_page = "search"
        self._row_repaint_hooks: list = []
        self._row_repaint_hooks_by_context: dict[str, list] = {
            "search": [],
            "library": [],
            "downloads": [],
            "queue": [],
        }
        self.active_eq_gains = self._load_eq_gains()

        # Theme & styling
        self.appearance = self.library.get_setting("appearance", "dark")
        if self.appearance not in ("dark", "light"):
            self.appearance = "dark"
        accent = self.library.get_setting("accent", default_accent())
        self.accent_name = accent if accent in ACCENT_DEFS else default_accent()
        self.palette = build_palette(self.appearance, self.accent_name)
        apply_appearance(self.appearance)
        ctk.ThemeManager.theme["CTkFont"]["family"] = "Segoe UI"

        saved_volume = self._load_int_setting("volume", 70)
        self._pre_mute_volume = max(1, saved_volume)
        try:
            self.queue.set_repeat(RepeatMode(self.library.get_setting("repeat", "off")))
        except ValueError:
            self.queue.set_repeat(RepeatMode.OFF)
        self.queue.set_shuffle(self.library.get_setting("shuffle", "0") == "1")

        self.player.set_volume(saved_volume)
        self.player.set_loop(self.queue.repeat_mode == RepeatMode.ONE)
        self.player.set_equalizer(self.active_eq_gains)
        self.player.set_volume_normalization(self.config_model.volume_normalization)

        # Build UI layout
        self._build_shell()
        self._build_player_bar()
        self.show_page("search")
        self._render_search_results()

        self.volume_slider.set(saved_volume)
        self._apply_repeat_ui()
        self._apply_shuffle_ui()
        self._restore_session()

        self._refresh_after_id = self.after(500, self._refresh_playback_state)
        self._bind_hotkeys()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        logger.info("Magic Music Player initialized successfully.")

    def dispatch(self, callback: Callable[[], None]) -> None:
        """Thread-safe dispatch of a callback to run on Tk's main event loop."""
        self._ui_queue.put(callback)

    def _poll_ui_queue(self) -> None:
        """Drain callbacks posted from background threads (mpv, worker, etc.)."""
        while not self._ui_queue.empty():
            try:
                fn = self._ui_queue.get_nowait()
                fn()
            except Exception as exc:
                logger.error("Error running dispatched UI callback: %s", exc)
        try:
            if self.winfo_exists():
                self._poll_after_id = self.after(25, self._poll_ui_queue)
        except Exception:
            pass

    # ------------------------------------------------------------- theming

    def _themed(self, widget: ctk.CTkBaseClass, **mapping: str):
        """Register a widget for live re-theming. mapping: option -> palette token."""
        widget_ref = weakref.ref(widget)

        def apply(pal: Palette) -> bool:
            widget = widget_ref()
            if widget is None:
                return False
            try:
                if not widget.winfo_exists():
                    return False
            except Exception:
                return False
            options = {}
            for option, token in mapping.items():
                value = getattr(pal, token, None)
                if value is not None:
                    options[option] = value
            if options:
                widget.configure(**options)
            return True

        self._themers.append(apply)
        apply(self.palette)
        return widget

    def _icon(self, name: str, size: int, color_token: str = "text") -> ctk.CTkLabel:
        label = ctk.CTkLabel(text=self.icons.glyph(name), font=self.icons.font(size))
        return self._themed(label, text_color=color_token)

    def _apply_theme(self) -> None:
        self.palette = build_palette(self.appearance, self.accent_name)
        alive = []
        for apply_fn in self._themers:
            try:
                if apply_fn(self.palette):
                    alive.append(apply_fn)
            except Exception:
                continue
        self._themers = alive
        apply_appearance(self.appearance)
        self.configure(fg_color=self.palette.bg)
        self._refresh_nav_active()
        self._apply_repeat_ui()
        self._apply_shuffle_ui()
        self._update_heart_current()
        if hasattr(self, "player_bar"):
            self.player_bar.update_volume_ui(int(self.volume_slider.get()), self._muted)
            self.player_bar.update_sleep_timer_ui(self.is_sleep_timer_active())
        self._render_all_pages()

    def _cycle_theme(self) -> None:
        self.appearance = "light" if self.appearance == "dark" else "dark"
        self.library.set_setting("appearance", self.appearance)
        self._apply_theme()

    # --------------------------------------------------------------- shell

    def _build_shell(self) -> None:
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        sidebar = self._themed(ctk.CTkFrame(self, width=190, corner_radius=0), fg_color="surface")
        sidebar.grid(row=0, column=0, sticky="nsw")
        sidebar.grid_propagate(False)
        sidebar.grid_columnconfigure(0, weight=1)

        brand = ctk.CTkFrame(sidebar, fg_color="transparent")
        brand.grid(row=0, column=0, sticky="ew", padx=18, pady=(20, 6))
        brand_label = ctk.CTkLabel(
            brand,
            text="Magic Music",
            font=ctk.CTkFont(size=19, weight="bold"),
            justify="left",
            text_color=self.palette.text,
        )
        brand_label.pack(anchor="w")
        self._themed(brand_label, text_color="text")
        subtitle = ctk.CTkLabel(brand, text="M M P   \u00b7   light & ad-free", font=ctk.CTkFont(size=11))
        self._themed(subtitle, text_color="muted").pack(anchor="w")

        ctk.CTkFrame(sidebar, fg_color="transparent", height=10).grid(row=1, column=0)

        nav_specs = (
            ("search", "search", "Search"),
            ("library", "library", "Library"),
            ("downloads", "download", "Downloads"),
            ("upnext", "add", "Up Next"),
            ("lyrics", "music_note", "Lyrics"),
        )
        for row_index, (key, glyph_name, label) in enumerate(nav_specs, start=2):
            button = ctk.CTkButton(
                sidebar,
                text=("  " + self.icons.glyph(glyph_name) + "   " + label)
                if self.icons.available()
                else ("  " + label),
                anchor="w",
                height=40,
                corner_radius=8,
                font=ctk.CTkFont(size=13),
                fg_color="transparent",
                hover_color=self.palette.hover,
                text_color=self.palette.muted,
                command=lambda k=key: self.show_page(k),
            )
            button.grid(row=row_index, column=0, sticky="ew", padx=12, pady=2)
            self._themed(button, hover_color="hover")
            self._nav_items[key] = {"button": button}

        sidebar.grid_rowconfigure(len(nav_specs) + 2, weight=1)

        bottom = ctk.CTkFrame(sidebar, fg_color="transparent")
        bottom.grid(row=99, column=0, sticky="ews", padx=12, pady=14)
        bottom.grid_columnconfigure(0, weight=1)

        theme_button = ctk.CTkButton(
            bottom,
            text=self.icons.glyph("moon" if self.appearance == "dark" else "brightness")
            if self.icons.available()
            else ("Light" if self.appearance == "dark" else "Dark"),
            width=40,
            height=34,
            corner_radius=8,
            fg_color=self.palette.idle,
            hover_color=self.palette.idle_hover,
            text_color=self.palette.text,
            font=self.icons.font(14) if self.icons.available() else ctk.CTkFont(size=12),
            command=self._cycle_theme,
        )
        theme_button.pack(side="left")
        self.theme_button = theme_button

        mini_button = ctk.CTkButton(
            bottom,
            text="\u2922",
            width=36,
            height=34,
            corner_radius=8,
            fg_color=self.palette.idle,
            hover_color=self.palette.idle_hover,
            text_color=self.palette.text,
            font=ctk.CTkFont(size=14),
            command=self.open_mini_player,
        )
        mini_button.pack(side="left", padx=(4, 0))
        self.mini_button = mini_button

        settings_button = ctk.CTkButton(
            bottom,
            text=self.icons.glyph("settings") if self.icons.available() else "Settings",
            width=40,
            height=34,
            corner_radius=8,
            fg_color=self.palette.idle,
            hover_color=self.palette.idle_hover,
            text_color=self.palette.text,
            font=self.icons.font(14) if self.icons.available() else ctk.CTkFont(size=12),
            command=self._open_settings,
        )
        settings_button.pack(side="right")
        for btn in (theme_button, mini_button, settings_button):
            self._themed(btn, fg_color="idle", hover_color="idle_hover", text_color="text")

        # Container for pages
        self.pages: dict[str, ctk.CTkFrame] = {}
        container = self._themed(ctk.CTkFrame(self, corner_radius=0), fg_color="bg")
        container.grid(row=0, column=1, sticky="nsew")
        container.grid_columnconfigure(0, weight=1)
        container.grid_rowconfigure(0, weight=1)

        # Build views into individual pages
        page_search = ctk.CTkFrame(container, fg_color="transparent")
        page_search.grid(row=0, column=0, sticky="nsew")
        self.pages["search"] = page_search
        self.search_view = SearchView(self, page_search)

        page_library = ctk.CTkFrame(container, fg_color="transparent")
        page_library.grid(row=0, column=0, sticky="nsew")
        self.pages["library"] = page_library
        self.library_view = LibraryView(self, page_library)

        page_downloads = ctk.CTkFrame(container, fg_color="transparent")
        page_downloads.grid(row=0, column=0, sticky="nsew")
        self.pages["downloads"] = page_downloads
        self.downloads_view = DownloadsView(self, page_downloads)

        page_queue = ctk.CTkFrame(container, fg_color="transparent")
        page_queue.grid(row=0, column=0, sticky="nsew")
        self.pages["upnext"] = page_queue
        self.queue_view = QueueView(self, page_queue)

        page_lyrics = ctk.CTkFrame(container, fg_color="transparent")
        page_lyrics.grid(row=0, column=0, sticky="nsew")
        self.pages["lyrics"] = page_lyrics
        self.lyrics_view = LyricsView(self, page_lyrics)

        # Backward compatibility properties
        self.search_entry = self.search_view.search_entry
        self.search_var = self.search_view.search_var
        self.search_button = self.search_view.search_button
        self.results_frame = self.search_view.results_frame
        self.library_frame = self.library_view.library_frame
        self.library_segment = self.library_view.library_segment
        self.downloads_frame = self.downloads_view.downloads_frame
        self.downloads_count_label = self.downloads_view.downloads_count_label
        self.queue_frame = self.queue_view.queue_frame
        self.queue_count_label = self.queue_view.queue_count_label

    def _refresh_nav_active(self) -> None:
        pal = self.palette
        for key, item in self._nav_items.items():
            active = key == self.active_page
            item["button"].configure(
                fg_color=pal.accent_subtle if active else "transparent",
                text_color=pal.accent if active else pal.muted,
                hover_color=pal.hover if not active else pal.accent_subtle,
            )
        if hasattr(self, "theme_button"):
            self.theme_button.configure(
                text=self.icons.glyph("moon" if self.appearance == "dark" else "brightness")
                if self.icons.available()
                else ("Light" if self.appearance == "dark" else "Dark")
            )

    def show_page(self, key: str) -> None:
        if key not in self.pages:
            return
        self.active_page = key
        self.pages[key].tkraise()
        self._refresh_nav_active()
        if key == "library":
            self.library_view.render_if_dirty()
        elif key == "downloads":
            self.downloads_view.render_if_dirty()
        elif key == "upnext":
            self.queue_view.render_if_dirty()
        elif key == "lyrics":
            self.lyrics_view.render()
        elif key == "search":
            if self._search_results_dirty:
                self._render_search_results()
                self._search_results_dirty = False
            self.search_entry.focus_set()

    def _render_all_pages(self) -> None:
        self._render_search_results()
        self._search_results_dirty = False
        self.library_view.invalidate()
        self.library_view.render()
        self.downloads_view.invalidate()
        self.downloads_view.render()
        self.queue_view.invalidate()
        self.queue_view.render()
        self._repaint_rows()

    def _build_player_bar(self) -> None:
        self.player_bar = PlayerBarComponent(self, self)

        # Expose convenient references for compatibility
        self.play_button = self.player_bar.play_button
        self.prev_button = self.player_bar.prev_button
        self.next_button = self.player_bar.next_button
        self.shuffle_button = self.player_bar.shuffle_button
        self.repeat_button = self.player_bar.repeat_button
        self.seek_slider = self.player_bar.seek_slider
        self.volume_slider = self.player_bar.volume_slider
        self.position_label = self.player_bar.position_label
        self.duration_label = self.player_bar.duration_label
        self.download_progress = self.player_bar.download_progress
        self.heart_current_button = self.player_bar.heart_button
        self.download_current_button = self.player_bar.download_button
        self.lyrics_button = self.player_bar.lyrics_button
        self.radio_button = self.player_bar.radio_button
        self.player_bar.update_radio_ui(self.auto_radio_enabled)
        self.track_title_label = self.player_bar.track_title_label
        self.track_artist_label = self.player_bar.track_artist_label
        self.bar_art_label = self.player_bar.art_label

    # ------------------------------------------------------------ thumbnails & art

    def _make_art_label(self, parent: ctk.CTkFrame, track: Track, size: int) -> ctk.CTkLabel:
        label = ctk.CTkLabel(
            parent,
            text=self.icons.glyph("music_note"),
            font=self.icons.font(int(size * 0.42)),
            width=size,
            height=size,
            corner_radius=8,
            fg_color=self.palette.surface_alt,
            text_color=self.palette.muted,
        )
        if track.thumbnail_url:
            self._request_art(track, label, size)
        return label

    def _request_art(self, track: Track, label: ctk.CTkLabel, size: int) -> None:
        key = self.thumbnails.cache_key(track)
        cache_key = f"{key}@{size}"
        cached_image = self._art_cache.get(cache_key)
        if cached_image is not None:
            try:
                if label.winfo_exists():
                    label.configure(image=cached_image, text="")
            except Exception:
                pass
            return

        def deliver(resolved_key: str, png_path: Path | None) -> None:
            self.after(0, lambda: self._deliver_art(resolved_key, png_path))

        self._art_labels.setdefault(key, []).append((label, size))
        cached = self.thumbnails.cached_png(track)
        if cached is not None:
            self._deliver_art(key, cached)
            return
        self.thumbnails.load_async(track, self.worker, deliver)

    def _deliver_art(self, key: str, png_path: Path | None) -> None:
        if png_path is None:
            self._art_labels.pop(key, None)
            return
        pending = self._art_labels.pop(key, [])
        for label, size in pending:
            cache_key = f"{key}@{size}"
            image = self._art_cache.get(cache_key)
            if image is None:
                try:
                    from PIL import Image

                    pil_image = self.thumbnails.get_cached_pil(key)
                    if pil_image is None and png_path is not None:
                        pil_image = Image.open(png_path)
                    image = ctk.CTkImage(light_image=pil_image, size=(size, size))
                except Exception:
                    continue
                if len(self._art_cache) > 240:
                    self._art_cache.clear()
                self._art_cache[cache_key] = image
            try:
                if label.winfo_exists():
                    label.configure(image=image, text="")
            except Exception:
                continue

    # ------------------------------------------------------------ track rows

    def _track_row(
        self,
        parent: ctk.CTkFrame,
        track: Track,
        context: str,
        index: int = 0,
        trailing: str | None = None,
    ) -> ctk.CTkFrame:
        return TrackRow.create(self, parent, track, context, index, trailing)

    def _row_icon_button(
        self, parent: ctk.CTkFrame, glyph_name: str, color_token: str, command
    ) -> ctk.CTkButton:
        return TrackRow._icon_button(self, parent, glyph_name, color_token, command)

    # -------------------------------------------------------------- search

    def _start_search(self, force_refresh: bool = False) -> None:
        query = self.search_view.search_controller.text.strip()
        if not query:
            return
        self._cancel_pending_search_partial()
        self.show_page("search")
        self._search_generation += 1
        generation = self._search_generation
        self.search_view.reset_provider_status()
        if self.search_future is not None and not self.search_future.done():
            self.search_future.cancel()
        self._last_searched_query = query
        self._remember_search(query)
        cached = self.search_service.get_cached_search(query) if not force_refresh else None
        if cached is not None:
            self._search_using_cache_generation = generation
            self._search_results_pending = False
            self.last_results = cached
            self._search_message = None
            self.search_view.render_results(cached)
            self._search_results_dirty = False
            self.search_button.configure(state="normal", text="Search")
            for provider in ("YouTube", "YouTube Music", "SoundCloud"):
                cnt = sum(1 for t in cached if t.source == provider)
                self.search_view.set_provider_status(provider, "done", cnt, 0.0)
            self.toast(f"Found {len(cached)} tracks (instant)")
        else:
            self._search_using_cache_generation = None
            self._search_results_pending = True
            self._search_message = "Searching across YouTube, YouTube Music, and SoundCloud…"
            self.search_button.configure(state="normal", text="Searching…")
            if not self.last_results:
                self.search_view.render_results([], message=self._search_message)
            self._search_results_dirty = False

        def show_partial(tracks: list[Track]) -> None:
            self.dispatch(lambda: self._queue_search_partial_results(tracks, generation))

        def provider_status(status: ProviderSearchStatus) -> None:
            self.dispatch(lambda: self._update_search_provider_status(status, generation))

        self.search_future = self.worker.submit(
            self.search_service.search(
                query,
                refresh=bool(force_refresh or cached is None),
                on_partial=show_partial,
                on_provider_status=provider_status,
            ),
            lambda future, gen=generation: self.dispatch(
                lambda: self._finish_search(future, gen)
            ),
        )

    def _on_search_return(self) -> None:
        current = self.search_view.search_controller.text.strip()
        if current and current == getattr(self, "_last_searched_query", None) and self.last_results:
            self.show_page("search")
            return
        self._start_search()

    def _show_partial_search_results(self, tracks: list[Track], generation: int) -> None:
        if (
            generation != self._search_generation
            or generation == self._search_using_cache_generation
            or not tracks
        ):
            return
        if tracks != self.last_results or self._search_results_pending:
            self.last_results = tracks
            self._search_results_pending = False
            self._search_message = None
            if self.active_page == "search":
                self.search_view.render_results(tracks)
                self._search_results_dirty = False
            else:
                self._search_results_dirty = True
        self.search_button.configure(state="normal", text="Updating…")

    def _queue_search_partial_results(self, tracks: list[Track], generation: int) -> None:
        if (
            generation != self._search_generation
            or generation == self._search_using_cache_generation
            or not tracks
        ):
            return
        self._search_partial_snapshot = (tracks, generation)
        if self._search_partial_after_id is None:
            # Idle coalescing combines callbacks drained in one queue pass without
            # adding a fixed delay to the first provider's results.
            self._search_partial_after_id = self.after_idle(
                lambda gen=generation: self._flush_search_partial_results(gen)
            )

    def _flush_search_partial_results(self, generation: int) -> None:
        self._search_partial_after_id = None
        pending = self._search_partial_snapshot
        self._search_partial_snapshot = None
        if pending is None or pending[1] != generation or generation != self._search_generation:
            return
        self._show_partial_search_results(pending[0], generation)

    def _cancel_pending_search_partial(self) -> None:
        if self._search_partial_after_id is not None:
            try:
                self.after_cancel(self._search_partial_after_id)
            except Exception:
                pass
        self._search_partial_after_id = None
        self._search_partial_snapshot = None

    def _update_search_provider_status(self, status: ProviderSearchStatus, generation: int) -> None:
        if generation != self._search_generation:
            return
        self.search_view.set_provider_status(
            status.provider,
            status.state,
            status.result_count,
            status.duration_seconds,
        )

    def _finish_search(self, future: Future, generation: int) -> None:
        if generation != self._search_generation:
            return
        self._flush_search_partial_results(generation)
        self.search_button.configure(state="normal", text="Search")
        was_showing_cache = generation == self._search_using_cache_generation
        was_pending = self._search_results_pending
        self._search_using_cache_generation = None
        self._search_results_pending = False
        try:
            tracks = future.result()
        except Exception as exc:
            logger.error("Search failed: %s", exc)
            if not was_showing_cache:
                self.last_results = []
                message = f"Search failed: {str(exc)[:60]}"
                self._search_message = message
                if self.active_page == "search":
                    self.search_view.render_results([], message=message)
                    self._search_results_dirty = False
                else:
                    self._search_results_dirty = True
            else:
                self.toast("Refresh failed; keeping recent results.")
            return

        changed = tracks != self.last_results
        self.last_results = tracks
        if not tracks:
            self._search_message = "No tracks found. Try a different query."
            if self.active_page == "search":
                self.search_view.render_results([], message=self._search_message)
                self._search_results_dirty = False
            else:
                self._search_results_dirty = True
            return

        self._search_message = None
        if self.active_page == "search" and (changed or self._search_results_dirty or was_pending):
            self.search_view.render_results(tracks)
            self._search_results_dirty = False
        elif self.active_page != "search":
            self._search_results_dirty = True
        self.toast(f"Found {len(tracks)} tracks")

        # Predictively pre-warm the top search result for instant zero-wait playback
        if tracks:
            top_track = tracks[0]
            if (
                not top_track.id.startswith("local:")
                and self.stream_extractor.get_cached_stream(top_track.webpage_url) is None
            ):
                self.worker.submit(
                    self.stream_extractor.get_audio_stream(top_track.webpage_url),
                    lambda _f: None,
                )

    def _load_recent_searches(self) -> list[str]:
        raw = self.library.get_setting("recent_searches", "[]") or "[]"
        try:
            values = json.loads(raw)
        except (TypeError, json.JSONDecodeError):
            return []
        if not isinstance(values, list):
            return []
        return [value.strip() for value in values if isinstance(value, str) and value.strip()][:5]

    def _remember_search(self, query: str) -> None:
        self.recent_searches = [query] + [item for item in self.recent_searches if item.casefold() != query.casefold()]
        self.recent_searches = self.recent_searches[:5]
        try:
            self.library.set_setting("recent_searches", json.dumps(self.recent_searches, ensure_ascii=False))
        except Exception as exc:
            logger.warning("Could not save recent searches: %s", exc)
        self.search_view.refresh_recent_searches()

    def _clear_recent_searches(self) -> None:
        self.recent_searches.clear()
        try:
            self.library.set_setting("recent_searches", "[]")
        except Exception as exc:
            logger.warning("Could not clear saved recent searches: %s", exc)
        self.search_view.refresh_recent_searches()

    def _render_search_results(self, message: str | None = None) -> None:
        self.search_view.render_results(self.last_results, message if message is not None else self._search_message)

    # ------------------------------------------------------------- library

    def _render_library_page(self) -> None:
        self.library_view.render()

    # ------------------------------------------------------------ downloads

    def _render_downloads_page(self) -> None:
        self.downloads_view.render()

    def _play_local_file(self, path_str: str | None) -> None:
        if not path_str:
            return
        path = Path(path_str)
        if not path.exists():
            self.toast("File no longer exists.")
            return
        previous_track_id = self.current_track.id if self.current_track is not None else None
        self.play_generation += 1
        self.current_track = None
        self._repaint_rows({previous_track_id} if previous_track_id else set())
        self.current_stream_url = str(path)
        self.player_bar.set_track_info(None)
        self.play_button.configure(state="normal", text=self._glyph_or("pause"))
        self.track_title_label.configure(text=table_text(path.stem, 36))
        self.track_artist_label.configure(text="Local file")
        self.download_current_button.configure(state="disabled")
        self.heart_current_button.configure(state="disabled", text=self._glyph_or("heart"))
        self.player.play(str(path))
        self.toast(f"Playing {table_text(path.stem, 40)}")

    def _open_downloads_folder(self) -> None:
        os_start_file(self.config_model.download_dir)

    # ---------------------------------------------------------------- queue

    def _enqueue_row(self, track: Track) -> None:
        self.queue.add(track)
        self.queue_view.invalidate()
        self.toast(f"Added to Up Next: {table_text(track.title, 40)}")
        if self.active_page == "upnext":
            self.queue_view.render()

    def _play_next(self, track: Track) -> None:
        was_empty = len(self.queue) == 0
        self.queue.play_next(track)
        self.queue_view.invalidate()
        if self.active_page == "upnext":
            self.queue_view.render()
        self.toast(f"Play next: {table_text(track.title, 40)}")
        if was_empty or self.current_track is None:
            self._begin_playback(track)

    def _copy_link(self, track: Track) -> None:
        url = track.webpage_url or ""
        self.clipboard_clear()
        self.clipboard_append(url)
        self.toast("Link copied to clipboard.")

    def _open_in_browser(self, track: Track) -> None:
        import webbrowser
        url = track.webpage_url
        if url and (url.startswith("http://") or url.startswith("https://")):
            webbrowser.open(url)
        else:
            self.toast("No web link available.")

    def _search_artist(self, artist: str) -> None:
        clean = artist.strip()
        if not clean:
            return
        self.show_page("search")
        self.search_view.search_controller.set_text(clean)
        self._start_search()

    def _show_in_explorer(self, file_path: str) -> None:
        import subprocess
        path = Path(file_path).resolve()
        if path.exists():
            subprocess.Popen(f'explorer /select,"{path}"')
        else:
            self.toast("File not found on disk.")

    def _delete_downloaded_file(self, file_path: str) -> None:
        path = Path(file_path).resolve()
        try:
            if path.exists():
                if self.current_track and (
                    self.current_track.webpage_url == file_path
                    or self.current_stream_url == str(path)
                    or self.current_track.webpage_url == str(path)
                ):
                    self.player.stop()
                    self.current_stream_url = None
                    if hasattr(self, "play_button"):
                        self.play_button.configure(text=self._glyph_or("play"))
                path.unlink()
                self.toast(f"Deleted {path.name}")
                self.downloads_view.refresh()
            else:
                self.toast("File not found.")
        except Exception as exc:
            logger.warning("Could not delete file %s: %s", path, exc)
            self.toast(f"Error deleting file: {exc}")

    def _export_queue_playlist(self, target_path: Path | str | None = None) -> Path | None:
        snapshot = self.queue.snapshot()
        if not snapshot.tracks:
            self.toast("Queue is empty.")
            return None
        if target_path is None:
            from tkinter import filedialog
            filename = filedialog.asksaveasfilename(
                title="Save Queue as Playlist",
                defaultextension=".m3u",
                filetypes=[("M3U Playlist", "*.m3u"), ("All Files", "*.*")],
                initialfile="queue.m3u",
            )
            if not filename:
                return None
            target_path = Path(filename)
        else:
            target_path = Path(target_path)

        try:
            lines = ["#EXTM3U\n"]
            for t in snapshot.tracks:
                dur = int(t.duration) if t.duration else -1
                artist_title = f"{t.artist} - {t.title}" if t.artist else t.title
                lines.append(f"#EXTINF:{dur},{artist_title}\n")
                lines.append(f"{t.webpage_url}\n")
            target_path.write_text("".join(lines), encoding="utf-8")
            self.toast(f"Saved playlist: {target_path.name}")
            return target_path
        except Exception as exc:
            logger.error("Could not export playlist: %s", exc)
            self.toast(f"Error saving playlist: {exc}")
            return None

    # -------------------------------------------------------- sleep timer

    def set_sleep_timer(self, minutes: int | None = None, end_of_track: bool = False) -> None:
        self.cancel_sleep_timer()
        if end_of_track:
            self._sleep_timer_end_of_track = True
            self.toast("Sleep timer set: stop at end of track.")
        elif minutes and minutes > 0:
            self._sleep_timer_minutes = minutes
            self._sleep_timer_end_time = time.monotonic() + minutes * 60
            self._sleep_timer_after_id = self.after(int(minutes * 60 * 1000), self._on_sleep_timer_fired)
            self.toast(f"Sleep timer set: {minutes} minutes.")
        if hasattr(self, "player_bar") and hasattr(self.player_bar, "update_sleep_timer_ui"):
            self.player_bar.update_sleep_timer_ui(self.is_sleep_timer_active())

    def cancel_sleep_timer(self, toast: bool = False) -> None:
        if self._sleep_timer_after_id:
            try:
                self.after_cancel(self._sleep_timer_after_id)
            except Exception:
                pass
            self._sleep_timer_after_id = None
        self._sleep_timer_end_of_track = False
        self._sleep_timer_end_time = None
        self._sleep_timer_minutes = None
        if hasattr(self, "player_bar") and hasattr(self.player_bar, "update_sleep_timer_ui"):
            self.player_bar.update_sleep_timer_ui(False)
        if toast:
            self.toast("Sleep timer turned off.")

    def is_sleep_timer_active(self) -> bool:
        return self._sleep_timer_end_of_track or (self._sleep_timer_after_id is not None)

    def _on_sleep_timer_fired(self) -> None:
        self.cancel_sleep_timer()
        self.player.stop()
        if hasattr(self, "play_button"):
            self.play_button.configure(text=self._glyph_or("play"))
        self.toast("Sleep timer: stopped playback.")

    def _restore_session(self) -> None:
        try:
            session = self.library.load_session()
            if not session or not session.get("tracks"):
                return
            tracks = [
                Track(
                    id=d["id"],
                    title=d["title"],
                    artist=d.get("artist", ""),
                    duration=d.get("duration"),
                    source=d.get("source", "Web"),
                    webpage_url=d.get("webpage_url", ""),
                    thumbnail_url=d.get("thumbnail_url"),
                )
                for d in session["tracks"]
            ]
            self.queue.clear()
            for t in tracks:
                self.queue.add(t)
            idx = session.get("current_index", -1)
            if 0 <= idx < len(tracks):
                self.queue.jump_to(idx)
                current = self.queue.current
                if current is not None:
                    self.current_track = current
                    if hasattr(self, "player_bar"):
                        self.player_bar.set_track_info(current)
                    if hasattr(self, "track_title_label"):
                        self.track_title_label.configure(text=table_text(current.title, 36))
                    if hasattr(self, "track_artist_label"):
                        self.track_artist_label.configure(text=table_text(current.artist or current.source, 28))
                    saved_pos = float(session.get("position", 0.0))
                    if saved_pos > 0:
                        self._pending_restore_position = saved_pos
                        if hasattr(self, "player_bar") and hasattr(self.player_bar, "position_label"):
                            self.player_bar.position_label.configure(text=format_time(saved_pos))
                            if current.duration and current.duration > 0:
                                self.player_bar.seek_slider.set(saved_pos / current.duration)
            self.queue_view.invalidate()
        except Exception as exc:
            logger.warning("Error restoring session: %s", exc)

    def _jump_queue(self, play_index: int) -> None:
        track = self.queue.jump_to(play_index)
        if track is None:
            return
        self.queue_view.invalidate()
        self._begin_playback(track)
        if self.active_page == "upnext":
            self.queue_view.render()

    def _remove_queue_item(self, play_index: int) -> bool:
        removed = self.queue.remove_at(play_index)
        if removed:
            self.queue_view.invalidate()
            if self.active_page == "upnext":
                self.queue_view.render_if_dirty()
        return removed

    def _clear_queue(self) -> None:
        self.queue.clear()
        self.queue_view.invalidate()
        if self.active_page == "upnext":
            self.queue_view.render_if_dirty()
        self.toast("Queue cleared.")

    def _render_queue_page(self) -> None:
        self.queue_view.render()

    # ------------------------------------------------------------- playback

    def _play_track(self, track: Track) -> None:
        self.queue.play_now(track)
        self.queue_view.invalidate()
        if self.active_page == "upnext":
            self.queue_view.render()
        self._begin_playback(track)

    def _begin_playback(self, track: Track, is_retry: bool = False) -> None:
        self.play_generation += 1
        self.queue_view.invalidate()
        generation = self.play_generation
        previous_track_id = self.current_track.id if self.current_track is not None else None
        self.current_track = track
        changed_track_ids = {track.id}
        if previous_track_id is not None:
            changed_track_ids.add(previous_track_id)
        self._repaint_rows(changed_track_ids)
        self._current_track_retried = is_retry

        # Fast-path 1: Local downloaded track (0ms)
        clean_url = track.webpage_url[6:] if track.webpage_url.startswith("local:") else track.webpage_url
        if not clean_url.startswith("http://") and not clean_url.startswith("https://") and Path(clean_url).is_file():
            self._start_playing_stream(clean_url, {}, track)
            return

        # Fast-path 2: On-disk audio cache (0ms)
        if not is_retry:
            cached_file = self.cache_manager.get_cached_audio(track.id)
            if cached_file and cached_file.is_file():
                logger.debug("Disk audio cache hit for %s", track.id)
                self._start_playing_stream(str(cached_file), {}, track)
                return

        # Fast-path 3: In-memory stream URL cache (<1ms)
        if not is_retry:
            cached_stream = self.stream_extractor.get_cached_stream(track.webpage_url)
            if cached_stream is not None:
                logger.debug("In-memory stream cache hit for %s", track.webpage_url)
                self._start_playing_stream(cached_stream.url, cached_stream.headers, track)
                return

        # Network path: scrape via yt-dlp
        self.player_bar.set_track_info(track, status_prefix="Retrying" if is_retry else "Loading")
        self.play_button.configure(state="disabled", text="")
        self.toast("Refreshing stream..." if is_retry else "Extracting audio stream...")
        self.worker.submit(
            self.stream_extractor.get_audio_stream(track.webpage_url),
            lambda future, gen=generation: self.dispatch(lambda: self._apply_stream(future, gen)),
        )

    def _start_playing_stream(self, stream_url: str, headers: dict[str, str], track: Track) -> None:
        self.current_stream_url = stream_url
        self.player.play(stream_url, headers)
        restore_pos = getattr(self, "_pending_restore_position", None)
        if restore_pos is not None:
            self._pending_restore_position = None
            if restore_pos > 0:
                self.after(200, lambda p=restore_pos: self.player.seek_absolute(p))
        self.play_button.configure(state="normal", text=self._glyph_or("pause"))
        self.player_bar.set_track_info(track)
        try:
            self.library.record_play(track)
            self.library_view.invalidate()
        except Exception as exc:
            logger.warning("Could not record play: %s", exc)
        self._update_heart_current()
        if self.active_page == "upnext":
            self.queue_view.render()
        elif self.active_page == "lyrics":
            self.lyrics_view.render(force=True)
        self.prefetch_manager.check_prefetch()

    def _apply_stream(self, future: Future, generation: int) -> None:
        if generation != self.play_generation:
            return
        try:
            stream = future.result()
        except Exception as exc:
            logger.error("Stream extraction failed: %s", exc)
            self.toast(f"Playback failed: {str(exc)[:70]}")
            self.track_title_label.configure(text="Playback failed")
            self.play_button.configure(state="normal", text=self._glyph_or("play"))
            return

        if self.current_track is not None:
            self._start_playing_stream(stream.url, stream.headers, self.current_track)

    def _on_track_playback_error(self, error_msg: str) -> None:
        """Handle playback error or stream expiration reported by AudioPlayer."""
        logger.warning("AudioPlayer reported playback error: %s", error_msg)
        if self.current_track is not None and not self._current_track_retried:
            if not self.current_track.id.startswith("local:"):
                self.stream_extractor._stream_cache.pop(self.current_track.webpage_url, None)
                logger.info("Retrying stream extraction for %s", self.current_track.title)
                self._begin_playback(self.current_track, is_retry=True)
                return
        self.toast("Playback error.")
        self.play_button.configure(text=self._glyph_or("play"))

    def _on_track_finished(self) -> None:
        if self._sleep_timer_end_of_track:
            self.cancel_sleep_timer()
            self.player.stop()
            self.play_button.configure(text=self._glyph_or("play"))
            self.toast("Sleep timer: stopped at end of track.")
            return

        if self.queue.repeat_mode == RepeatMode.ONE:
            if self.current_track is not None:
                self._begin_playback(self.current_track)
            return
        next_track = self.queue.advance()
        if next_track is not None:
            self._begin_playback(next_track)
            return

        # Queue ended; check Endless Auto-Radio
        if getattr(self, "auto_radio_enabled", True) and self.current_track is not None:
            logger.info("Queue ended; triggering Auto-Radio for %s", self.current_track.title)
            self.toast("Auto-Radio: finding similar tracks...")
            self.worker.submit(
                self.search_service.get_related_tracks(self.current_track, limit=8),
                lambda future: self.dispatch(lambda: self._on_auto_radio_results(future)),
            )
            return

        self.play_button.configure(text=self._glyph_or("play"))
        self.toast("Queue finished.")

    def _on_auto_radio_results(self, future: Future) -> None:
        try:
            related = future.result()
        except Exception as exc:
            logger.warning("Auto-Radio search failed: %s", exc)
            related = []

        if not related:
            self.play_button.configure(text=self._glyph_or("play"))
            self.toast("Queue finished.")
            return

        for track in related:
            self.queue.add(track)
        self.queue_view.invalidate()
        if self.active_page == "upnext":
            self.queue_view.render()
        first_next = self.queue.advance()
        if first_next:
            self.toast(f"Radio playing: {table_text(first_next.title, 35)}")
            self._begin_playback(first_next)

    def _toggle_lyrics_view(self) -> None:
        self.show_page("search" if self.active_page == "lyrics" else "lyrics")

    def _toggle_auto_radio(self) -> None:
        self.auto_radio_enabled = not self.auto_radio_enabled
        self.library.set_setting("auto_radio", "1" if self.auto_radio_enabled else "0")
        if hasattr(self, "player_bar"):
            self.player_bar.update_radio_ui(self.auto_radio_enabled)
        self.toast("Auto-Radio: " + ("Enabled" if self.auto_radio_enabled else "Disabled"))

    def _next_track(self) -> None:
        next_track = self.queue.advance(ignore_repeat_one=True)
        if next_track is None:
            self.toast("End of queue.")
            return
        self.focus_set()
        self._begin_playback(next_track)

    def _prev_track(self) -> None:
        if self.queue.current is not None and self.player.state().position > 3.0:
            self.player.seek_absolute(0.0)
            return
        previous = self.queue.step_back()
        if previous is None:
            return
        self.focus_set()
        self._begin_playback(previous)

    def _toggle_pause(self) -> None:
        if self.current_stream_url is None:
            target = self.current_track or self.queue.current
            if target is not None:
                self._begin_playback(target)
                return
        paused = self.player.toggle_pause()
        self.play_button.configure(text=self._glyph_or("play" if paused else "pause"))
        self.focus_set()

    def _cycle_repeat(self) -> None:
        mode = self.queue.cycle_repeat()
        if self.player is not None:
            self.player.set_loop(mode == RepeatMode.ONE)
        self.library.set_setting("repeat", mode.value)
        self._apply_repeat_ui()
        labels = {"off": "Repeat: Off", "all": "Repeat: All", "one": "Repeat: One"}
        self.toast(labels.get(mode.value, f"Repeat: {mode.value}"))

    def _apply_repeat_ui(self) -> None:
        if not hasattr(self, "repeat_button"):
            return
        glyph = {"off": "repeat_all", "all": "repeat_all", "one": "repeat_one"}[
            self.queue.repeat_mode.value
        ]
        active = self.queue.repeat_mode != RepeatMode.OFF
        self.repeat_button.configure(
            text=self._glyph_or(glyph),
            fg_color=self.palette.accent if active else self.palette.idle,
            text_color="#ffffff" if active else self.palette.text,
        )
        suffix = {"off": "", "all": " \u00b7 all", "one": " \u00b7 one"}[self.queue.repeat_mode.value]
        self.repeat_button.configure(hover_color=self.palette.accent_hover if active else self.palette.idle_hover)
        self._repeat_tooltip = suffix

    def _toggle_shuffle(self) -> None:
        self.queue.set_shuffle(not self.queue.shuffle)
        self.queue_view.invalidate()
        self.library.set_setting("shuffle", "1" if self.queue.shuffle else "0")
        self._apply_shuffle_ui()
        if self.active_page == "upnext":
            self.queue_view.render()
        self.toast("Shuffle: " + ("On" if self.queue.shuffle else "Off"))

    def _apply_shuffle_ui(self) -> None:
        if not hasattr(self, "shuffle_button"):
            return
        active = self.queue.shuffle
        self.shuffle_button.configure(
            text=self._glyph_or("shuffle"),
            fg_color=self.palette.accent if active else self.palette.idle,
            text_color="#ffffff" if active else self.palette.text,
            hover_color=self.palette.accent_hover if active else self.palette.idle_hover,
        )

    def _update_heart_current(self) -> None:
        if not hasattr(self, "heart_current_button"):
            return
        if self.current_track is None:
            self.heart_current_button.configure(state="disabled", text=self._glyph_or("heart"))
            return
        favorite = self.library.is_favorite(self.current_track.id)
        self.heart_current_button.configure(
            state="normal",
            text=self._glyph_or("heart_filled" if favorite else "heart"),
            text_color=self.palette.accent if favorite else self.palette.muted,
        )

    def _toggle_heart_current(self) -> None:
        if self.current_track is None:
            return
        self._toggle_favorite(self.current_track)
        self._update_heart_current()

    def _repaint_rows(self, track_ids: set[str] | None = None) -> None:
        by_context = getattr(self, "_row_repaint_hooks_by_context", None)
        hook_groups = by_context.values() if by_context is not None else (getattr(self, "_row_repaint_hooks", []),)
        for hooks in hook_groups:
            for entry in list(hooks):
                if isinstance(entry, tuple) and len(entry) == 2:
                    track_id, hook = entry
                    if track_ids is not None and track_id not in track_ids:
                        continue
                else:
                    hook = entry
                    if track_ids is not None:
                        continue
                try:
                    hook()
                except Exception:
                    continue

    def _toggle_favorite(self, track: Track) -> None:
        now_favorite = not self.library.is_favorite(track.id)
        try:
            self.library.set_favorite(track, now_favorite)
        except Exception as exc:
            logger.error("Could not update favorites: %s", exc)
            self.toast(f"Could not update favorites: {str(exc)[:60]}")
            return
        self.toast(
            ("Added to favorites: " if now_favorite else "Removed from favorites: ")
            + table_text(track.title, 40)
        )
        self._repaint_rows({track.id})
        if self.current_track is not None and self.current_track.id == track.id:
            self._update_heart_current()
        self.library_view.invalidate()
        if self.active_page == "library":
            self.library_view.render()

    # -------------------------------------------------------- seek & volume

    def _set_volume(self, value: float) -> None:
        vol = int(value)
        if vol > 0:
            self._muted = False
        self.player.set_volume(vol)
        if hasattr(self, "volume_slider"):
            try:
                if int(self.volume_slider.get()) != vol:
                    self.volume_slider.set(vol)
            except Exception:
                pass
        if hasattr(self, "player_bar"):
            self.player_bar.update_volume_ui(vol, self._muted)

    def _persist_volume(self) -> None:
        try:
            self.library.set_setting("volume", str(int(self.volume_slider.get())))
        except Exception as exc:
            logger.warning("Could not persist volume setting: %s", exc)

    def _refresh_playback_state(self) -> None:
        try:
            if not self.winfo_exists():
                return
            state = self.player.state()
        except Exception:
            state = None
        if state is not None and hasattr(self, "player_bar"):
            self.player_bar.update_playback_state(state)
            if self.active_page == "lyrics" and hasattr(self, "lyrics_view"):
                self.lyrics_view.update_playback_position(state.position)
            if not state.paused and state.duration > 0 and (state.duration - state.position) < 30.0:
                if hasattr(self, "prefetch_manager"):
                    self.prefetch_manager.check_prefetch()
        try:
            if self.winfo_exists():
                self._refresh_after_id = self.after(200, self._refresh_playback_state)
        except Exception:
            pass

    def _glyph_or(self, name: str) -> str:
        if self.icons.available():
            return self.icons.glyph(name)
        return {
            "play": "\u25B6",
            "pause": "\u23F8",
            "prev": "|<",
            "next": ">|",
            "download": "\u2193",
            "heart": "\u2661",
            "heart_filled": "\u2665",
            "shuffle": "\u292E",
            "repeat_all": "\u21BB",
            "repeat_one": "\u21BB1",
            "volume": "\u266B",
            "radio": "\u221E",
            "timer": "\u23F2",
        }.get(name, name)

    def open_mini_player(self) -> None:
        if hasattr(self, "_mini_player") and self._mini_player is not None and self._mini_player.winfo_exists():
            self._mini_player.lift()
            return
        self.withdraw()
        self._mini_player = MiniPlayerWindow(self)

    # ------------------------------------------------------------ hotkeys

    def _bind_hotkeys(self) -> None:
        self.bind("<space>", self._hotkey_toggle_pause)
        self.bind("<Left>", self._hotkey_seek_back)
        self.bind("<Right>", self._hotkey_seek_forward)
        self.bind("<Up>", self._hotkey_volume_up)
        self.bind("<Down>", self._hotkey_volume_down)
        self.bind("<Control-Left>", self._hotkey_prev_track)
        self.bind("<Control-Right>", self._hotkey_next_track)
        self.bind("<Control-f>", self._hotkey_focus_search)
        self.bind("<Control-F>", self._hotkey_focus_search)
        self.bind("<Control-m>", lambda _e: self.open_mini_player())
        self.bind("<Control-M>", lambda _e: self.open_mini_player())
        self.bind("<Control-l>", lambda _e: self._toggle_lyrics_view())
        self.bind("<Control-L>", lambda _e: self._toggle_lyrics_view())
        self.bind("<Control-r>", lambda _e: self._toggle_auto_radio())
        self.bind("<Control-R>", lambda _e: self._toggle_auto_radio())
        self.bind("/", self._hotkey_focus_search)
        self.bind("m", self._hotkey_mute)
        self.bind("M", self._hotkey_mute)
        self.bind("n", self._hotkey_next_track)
        self.bind("N", self._hotkey_next_track)
        self.bind("p", self._hotkey_prev_track)
        self.bind("P", self._hotkey_prev_track)
        self.bind("d", self._hotkey_download_current)
        self.bind("D", self._hotkey_download_current)
        self.bind("f", self._hotkey_favorite_current)
        self.bind("F", self._hotkey_favorite_current)
        for number, page_key in enumerate(PAGES, start=1):
            self.bind(str(number), lambda _e, key=page_key: self._hotkey_switch_page(key))

        # Hardware media keys
        media_bindings = (
            ("<XF86AudioPlay>", lambda _e: self._hotkey_toggle_pause()),
            ("<XF86AudioPause>", lambda _e: self._hotkey_toggle_pause()),
            ("<XF86AudioNext>", lambda _e: self._hotkey_next_track()),
            ("<XF86AudioPrev>", lambda _e: self._hotkey_prev_track()),
            (
                "<XF86AudioStop>",
                lambda _e: (
                    self.player.stop(),
                    self.play_button.configure(text=self._glyph_or("play")),
                ),
            ),
            ("<XF86AudioMute>", lambda _e: self._hotkey_mute()),
            ("<XF86AudioRaiseVolume>", lambda _e: self._volume_step(5)),
            ("<XF86AudioLowerVolume>", lambda _e: self._volume_step(-5)),
        )
        for seq, handler in media_bindings:
            try:
                self.bind(seq, handler)
            except Exception:
                pass

    def _typing_focused(self) -> bool:
        widget = self.focus_get()
        if widget is None:
            return False
        if isinstance(widget, ctk.CTkEntry):
            return True
        return widget.winfo_class() in ("Entry", "TEntry", "TCombobox")

    def _guard_typing(self) -> bool:
        return self._typing_focused()

    def _hotkey_toggle_pause(self, _event: object = None) -> str | None:
        if self._typing_focused():
            return None
        self._toggle_pause()
        return "break"

    def _hotkey_seek(self, delta: float) -> str | None:
        if self._typing_focused():
            return None
        state = self.player.state()
        target = max(0.0, min(state.position + delta, state.duration or state.position + delta))
        self.player.seek_absolute(target)
        return "break"

    def _hotkey_seek_back(self, _event: object = None) -> str | None:
        return self._hotkey_seek(-5.0)

    def _hotkey_seek_forward(self, _event: object = None) -> str | None:
        return self._hotkey_seek(5.0)

    def _volume_step(self, delta: int) -> None:
        current = int(self.volume_slider.get())
        volume = max(0, min(100, current + delta))
        self.player.set_volume(volume)
        self.volume_slider.set(volume)
        self._persist_volume()
        if self._muted and volume > 0:
            self._muted = False
        if hasattr(self, "player_bar"):
            self.player_bar.update_volume_ui(volume, self._muted)
        self.toast(f"Volume {volume}%")

    def _hotkey_volume_up(self, _event: object = None) -> str | None:
        if self._typing_focused():
            return None
        self._volume_step(5)
        return "break"

    def _hotkey_volume_down(self, _event: object = None) -> str | None:
        if self._typing_focused():
            return None
        self._volume_step(-5)
        return "break"

    def _hotkey_mute(self, _event: object = None) -> str | None:
        if self._typing_focused():
            return None
        if self._muted:
            restore = max(1, getattr(self, "_pre_mute_volume", 70))
            self._muted = False
            self.player.set_volume(restore)
            self.volume_slider.set(restore)
            if hasattr(self, "player_bar"):
                self.player_bar.update_volume_ui(restore, False)
            self.toast(f"Unmuted \u00b7 {restore}%")
        else:
            self._muted = True
            self._pre_mute_volume = int(self.volume_slider.get())
            self.player.set_volume(0)
            self.volume_slider.set(0)
            if hasattr(self, "player_bar"):
                self.player_bar.update_volume_ui(0, True)
            self.toast("Muted")
        return "break"

    def _hotkey_next_track(self, _event: object = None) -> str | None:
        if self._typing_focused():
            return None
        self._next_track()
        return "break"

    def _hotkey_prev_track(self, _event: object = None) -> str | None:
        if self._typing_focused():
            return None
        self._prev_track()
        return "break"

    def _hotkey_download_current(self, _event: object = None) -> str | None:
        if self._typing_focused() or self.current_track is None:
            return None
        self._download_current()
        return "break"

    def _hotkey_favorite_current(self, _event: object = None) -> str | None:
        if self._typing_focused() or self.current_track is None:
            return None
        self._toggle_heart_current()
        return "break"

    def _hotkey_focus_search(self, _event: object = None) -> str | None:
        self.show_page("search")
        self.search_entry.focus_set()
        return "break"

    def _hotkey_switch_page(self, key: str) -> str | None:
        if self._typing_focused():
            return None
        self.show_page(key)
        return "break"

    # ------------------------------------------------------------ downloads

    def _download_current(self) -> None:
        if self.current_track is not None:
            self._download_track(self.current_track)

    def _download_track(self, track: Track) -> None:
        self.download_manager.enqueue(track)
        self.toast(f"Downloading: {table_text(track.title, 45)}")

    def _on_download_task_update(self, task: DownloadTask) -> None:
        active_cnt, queue_cnt, avg_pct = self.download_manager.aggregate_stats()
        if active_cnt > 0:
            self.download_progress.set(max(0.01, min(1.0, avg_pct / 100.0)))
            if task.status == DownloadStatus.DOWNLOADING and task.progress.percent > 0:
                parts = [f"{task.progress.percent:.0f}%"]
                if task.progress.speed_label:
                    parts.append(task.progress.speed_label)
                if task.progress.eta_label:
                    parts.append(f"ETA {task.progress.eta_label}")
                if self.active_page == "downloads" and hasattr(self, "downloads_view"):
                    try:
                        self.downloads_view.downloads_count_label.configure(
                            text=f"Downloading: {' · '.join(parts)}"
                        )
                    except Exception:
                        pass
        else:
            self.download_progress.set(0.0)

        if task.status == DownloadStatus.COMPLETED:
            self.downloads_view.invalidate()
            filename = task.result_path.name if task.result_path else "track"
            self.toast(f"Saved: {filename}")
            if self.active_page == "downloads":
                self.downloads_view.render()
        elif task.status == DownloadStatus.FAILED:
            self.toast(f"Download failed: {(task.error or '')[:60]}")

    # ------------------------------------------------------------ settings

    def _load_eq_gains(self) -> list[float]:
        preset = self.library.get_setting("eq_preset", "Flat")
        if preset in EQ_PRESETS:
            return list(EQ_PRESETS[preset])
        raw = self.library.get_setting("eq_gains", "")
        if raw:
            try:
                return normalize_eq_gains(float(value) for value in raw.split(","))
            except ValueError:
                pass
        return list(EQ_PRESETS["Flat"])

    def _open_settings(self) -> None:
        SettingsDialog.show(self)

    # ---------------------------------------------------------------- misc

    def toast(self, message: str) -> None:
        if self._toast_after is not None:
            try:
                self.after_cancel(self._toast_after)
            except Exception:
                pass
            self._toast_after = None
        if hasattr(self, "_toast_label") and self._toast_label is not None:
            try:
                self._toast_label.destroy()
            except Exception:
                pass
        label = ctk.CTkLabel(
            self,
            text=f"  {message}  ",
            corner_radius=16,
            fg_color=self.palette.surface,
            text_color=self.palette.text,
            font=ctk.CTkFont(size=12),
            height=32,
        )
        label.place(relx=0.5, rely=0.0, y=14, anchor="n")
        self._toast_label = label
        self._toast_after = self.after(2600, lambda: self._hide_toast(label))

    def _hide_toast(self, label: ctk.CTkLabel) -> None:
        try:
            if label.winfo_exists():
                label.destroy()
        except Exception:
            pass
        self._toast_after = None

    def _load_int_setting(self, key: str, default: int) -> int:
        raw = self.library.get_setting(key, str(default))
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return default

    def _on_close(self) -> None:
        if getattr(self, "_is_closed", False):
            return
        self._is_closed = True
        logger.info("Closing Magic Music Player...")
        for after_id in (
            getattr(self, "_poll_after_id", None),
            getattr(self, "_refresh_after_id", None),
            getattr(self, "_toast_after", None),
            getattr(self, "_search_partial_after_id", None),
        ):
            if after_id is not None:
                try:
                    self.after_cancel(after_id)
                except Exception:
                    pass
        self._poll_after_id = None
        self._refresh_after_id = None
        self._toast_after = None
        self._search_partial_after_id = None
        try:
            self._persist_volume()
            self.library.set_setting("repeat", self.queue.repeat_mode.value)
            self.library.set_setting("shuffle", "1" if self.queue.shuffle else "0")
            self.library.set_setting("auto_radio", "1" if getattr(self, "auto_radio_enabled", True) else "0")
            self.library.set_setting("appearance", self.appearance)
            self.library.set_setting("accent", self.accent_name)
            self.cancel_sleep_timer()
            try:
                snapshot = self.queue.snapshot()
                pos = float(self.player.state().position) if self.player else 0.0
                self.library.save_session(list(snapshot.tracks), snapshot.current_index, pos)
            except Exception as exc:
                logger.warning("Error saving session: %s", exc)
            self.player.shutdown()
            self.worker.stop()
            self.library.close()
        except Exception as exc:
            logger.warning("Error during close: %s", exc)
        finally:
            self.destroy()


def os_start_file(path: Path) -> None:
    import os
    import subprocess

    try:
        os.startfile(path)  # type: ignore[attr-defined]
    except AttributeError:
        subprocess.Popen(["xdg-open", str(path)])


def _set_windows_app_id() -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            app_id = "MagicMusicPlayer.MMP.Desktop"
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        except Exception as exc:
            logger.debug("Could not set AppUserModelID: %s", exc)


def _acquire_single_instance() -> bool:
    if sys.platform != "win32":
        return True
    import ctypes

    ctypes.windll.kernel32.CreateMutexW(None, False, "Local\\MagicMusicPlayerSingleInstance")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def _focus_existing_instance() -> None:
    if sys.platform != "win32":
        return
    import ctypes
    from ctypes import wintypes

    user32 = ctypes.windll.user32
    found = []
    proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length:
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            if buffer.value.startswith("Magic Music Player"):
                found.append(hwnd)
        return True

    user32.EnumWindows(proc(callback), 0)
    if found:
        user32.ShowWindow(found[0], 9)
        user32.SetForegroundWindow(found[0])


def main() -> None:
    setup_logging()
    _set_windows_app_id()

    if not _acquire_single_instance():
        _focus_existing_instance()
        return
    try:
        app = MagicMusicPlayerApp()
    except RuntimeError as exc:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Magic Music Player", str(exc))
        return
    app.mainloop()
