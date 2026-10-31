from __future__ import annotations

from typing import TYPE_CHECKING, Callable
import tkinter as tk

import customtkinter as ctk

from ...arabic import display_text
from ...thumbnails import THUMB_DISPLAY_SIZE

if TYPE_CHECKING:
    from ...app import MagicMusicPlayerApp
    from ...models import Track


def table_text(text: str, max_chars: int) -> str:
    clean = " ".join(text.split())
    if len(clean) > max_chars:
        clean = f"{clean[: max_chars - 3]}..."
    return display_text(clean)


class TrackRow:
    """Component for a single interactive track row."""

    @staticmethod
    def create(
        app: MagicMusicPlayerApp,
        parent: ctk.CTkFrame,
        track: Track,
        context: str,
        index: int = 0,
        trailing: str | None = None,
    ) -> ctk.CTkFrame:
        state = {
            "hover": False,
            "heart_button": None,
            "track": track,
            "index": index,
            "trailing": trailing,
            "title_label": None,
            "artist_label": None,
            "duration_label": None,
            "art_label": None,
            "art_url": track.thumbnail_url,
            "favorite": None,
            "favorite_color": None,
            "painted_color": None,
            "palette_text": None,
            "palette_muted": None,
            "palette_hover": None,
            "action_buttons": [],
        }
        playing = app.current_track is not None and app.current_track.id == track.id
        initial_color = app.palette.accent_subtle if playing else app.palette.surface_alt
        state["painted_color"] = initial_color

        row = ctk.CTkFrame(parent, corner_radius=8, fg_color=initial_color)
        row.grid(row=index, column=0, sticky="ew", pady=(0, 6), padx=(6, 10))
        row.grid_columnconfigure(1, weight=1)

        def repaint() -> None:
            current = state["track"]
            is_playing = app.current_track is not None and app.current_track.id == current.id
            if is_playing:
                color = app.palette.accent_subtle
            elif state["hover"]:
                color = app.palette.hover
            else:
                color = app.palette.surface_alt
            if state["painted_color"] != color:
                row.configure(fg_color=color)
                state["painted_color"] = color
            if state["palette_text"] != app.palette.text:
                title_label = state["title_label"]
                if title_label is not None:
                    title_label.configure(text_color=app.palette.text)
                state["palette_text"] = app.palette.text
            if state["palette_muted"] != app.palette.muted:
                for label_key in ("artist_label", "duration_label"):
                    label = state[label_key]
                    if label is not None:
                        label.configure(text_color=app.palette.muted)
                state["palette_muted"] = app.palette.muted
            if state["palette_hover"] != app.palette.hover:
                for button in state["action_buttons"]:
                    button.configure(hover_color=app.palette.hover)
                state["palette_hover"] = app.palette.hover
            for button in state["action_buttons"]:
                if button is not state["heart_button"] and getattr(button, "_mmp_text_color", None) != app.palette.muted:
                    button.configure(text_color=app.palette.muted)
                    button._mmp_text_color = app.palette.muted
            heart_button = state["heart_button"]
            if heart_button is not None:
                favorite = app.library.is_favorite(current.id)
                favorite_color = app.palette.accent if favorite else app.palette.muted
                if state["favorite"] != favorite or state["favorite_color"] != favorite_color:
                    options = {"text_color": favorite_color}
                    if state["favorite"] != favorite:
                        options["text"] = (
                            app.icons.glyph("heart_filled" if favorite else "heart")
                            if app.icons.available()
                            else app._glyph_or("heart_filled" if favorite else "heart")
                        )
                    heart_button.configure(**options)
                    state["favorite"] = favorite
                    state["favorite_color"] = favorite_color

        def on_play(_event=None) -> None:
            current = state["track"]
            if context == "downloads":
                app._play_local_file(current.webpage_url)
            elif context == "queue":
                app._jump_queue(state["index"])
            else:
                app._play_track(current)

        def on_hover_enter(_e=None) -> None:
            state["hover"] = True
            is_playing = app.current_track is not None and app.current_track.id == state["track"].id
            target = app.palette.accent_subtle if is_playing else app.palette.hover
            if state["painted_color"] != target:
                row.configure(fg_color=target)
                state["painted_color"] = target

        def on_hover_leave(_e=None) -> None:
            state["hover"] = False
            is_playing = app.current_track is not None and app.current_track.id == state["track"].id
            target = app.palette.accent_subtle if is_playing else app.palette.surface_alt
            if state["painted_color"] != target:
                row.configure(fg_color=target)
                state["painted_color"] = target

        def on_context_menu(event=None) -> tk.Menu:
            if getattr(app, "_active_track_menu", None) is not None:
                try:
                    app._active_track_menu.destroy()
                except Exception:
                    pass
            menu = tk.Menu(
                app,
                tearoff=0,
                bg=app.palette.surface,
                fg=app.palette.text,
                activebackground=app.palette.accent,
                activeforeground="#ffffff",
                relief="flat",
                bd=1,
            )
            app._active_track_menu = menu
            current = state["track"]

            menu.add_command(
                label="Play Next",
                command=lambda: app._play_next(current),
            )
            menu.add_command(
                label="Add to Queue",
                command=lambda: app._enqueue_row(current),
            )
            menu.add_separator()

            menu.add_command(
                label="Copy Link",
                command=lambda: app._copy_link(current),
            )
            if current.webpage_url and current.webpage_url.startswith("http"):
                menu.add_command(
                    label="Open in Browser",
                    command=lambda: app._open_in_browser(current),
                )

            if context != "downloads" and current.artist and current.artist.strip():
                menu.add_command(
                    label="Search Artist",
                    command=lambda: app._search_artist(current.artist),
                )

            menu.add_separator()
            if context != "downloads":
                menu.add_command(
                    label="Download",
                    command=lambda: app._download_track(current),
                )
            else:
                menu.add_command(
                    label="Show in Explorer",
                    command=lambda: app._show_in_explorer(current.webpage_url),
                )
                menu.add_command(
                    label="Delete File",
                    command=lambda: app._delete_downloaded_file(current.webpage_url),
                )

            if context == "queue":
                menu.add_separator()
                menu.add_command(
                    label="Remove from Queue",
                    command=lambda: app._remove_queue_item(state["index"]),
                )

            if event is not None and hasattr(event, "x_root") and hasattr(event, "y_root"):
                menu.post(event.x_root, event.y_root)
            return menu

        row.bind("<Enter>", on_hover_enter)
        row.bind("<Leave>", on_hover_leave)
        row.bind("<Button-1>", on_play)
        row.bind("<Button-3>", on_context_menu)
        row.configure(cursor="hand2")

        # Art label
        art = app._make_art_label(row, track, THUMB_DISPLAY_SIZE)
        art.grid(row=0, column=0, rowspan=2, padx=(10, 12), pady=8, sticky="ns")
        art.bind("<Button-1>", on_play)
        art.bind("<Button-3>", on_context_menu)

        # Title
        title_label = ctk.CTkLabel(
            row,
            text=table_text(track.title, 64),
            anchor="w",
            font=ctk.CTkFont(size=14, weight="bold"),
            text_color=app.palette.text,
        )
        title_label.grid(row=0, column=1, sticky="ew", pady=(9, 0))
        title_label.bind("<Button-1>", on_play)
        title_label.bind("<Button-3>", on_context_menu)
        state["title_label"] = title_label

        # Artist / subtitle
        if context == "downloads":
            subtitle_text = ""
        elif context == "search":
            subtitle_text = table_text(f"{track.artist}  ·  {track.source}", 52)
        else:
            subtitle_text = table_text(track.artist, 46)
        artist_label = ctk.CTkLabel(
            row,
            text=subtitle_text,
            anchor="w",
            font=ctk.CTkFont(size=12),
            text_color=app.palette.muted,
        )
        artist_label.grid(row=1, column=1, sticky="ew", pady=(0, 9))
        artist_label.bind("<Button-1>", on_play)
        artist_label.bind("<Button-3>", on_context_menu)
        state["artist_label"] = artist_label

        # Duration / Trailing text
        side_text = (trailing or "") if context == "downloads" else track.duration_label
        duration_label = ctk.CTkLabel(
            row,
            text=side_text,
            anchor="e",
            width=64 if context == "downloads" else 52,
            font=ctk.CTkFont(size=11),
            text_color=app.palette.muted,
        )
        duration_label.grid(row=0, column=2, rowspan=2, padx=(4, 8))
        duration_label.bind("<Button-3>", on_context_menu)
        state["duration_label"] = duration_label

        # Actions
        actions = ctk.CTkFrame(row, fg_color="transparent")
        actions.grid(row=0, column=3, rowspan=2, padx=(0, 10), pady=6)
        actions.bind("<Button-3>", on_context_menu)

        if context in ("search", "library"):
            favorite = app.library.is_favorite(track.id)
            heart = TrackRow._icon_button(
                app,
                actions,
                "heart_filled" if favorite else "heart",
                app.palette.accent if favorite else app.palette.muted,
                lambda: app._toggle_favorite(state["track"]),
            )
            state["heart_button"] = heart
            state["favorite"] = favorite
            state["favorite_color"] = app.palette.accent if favorite else app.palette.muted
            heart.pack(side="left", padx=2)
            state["action_buttons"].append(heart)

            queue_button = TrackRow._icon_button(
                app, actions, "add", app.palette.muted, lambda: app._enqueue_row(state["track"])
            )
            queue_button.pack(side="left", padx=2)
            state["action_buttons"].append(queue_button)

            download_button = TrackRow._icon_button(
                app, actions, "download", app.palette.muted, lambda: app._download_track(state["track"])
            )
            download_button.pack(side="left", padx=2)
            state["action_buttons"].append(download_button)

        elif context == "queue":
            remove_button = TrackRow._icon_button(
                app, actions, "close", app.palette.muted, lambda: app._remove_queue_item(state["index"])
            )
            remove_button.pack(side="left", padx=2)
            state["action_buttons"].append(remove_button)

        hooks_by_context = getattr(app, "_row_repaint_hooks_by_context", None)
        state["palette_text"] = app.palette.text
        state["palette_muted"] = app.palette.muted
        state["palette_hover"] = app.palette.hover
        row._mmp_state = state
        row._mmp_hidden = False
        row._mmp_repaint = repaint
        row._mmp_show_context_menu = on_context_menu
        row._mmp_track_id = track.id
        row._mmp_repaint_entry = (track.id, repaint)
        row._mmp_update = lambda new_track, new_index, new_trailing=None: TrackRow.update(
            app, row, new_track, context, new_index, new_trailing
        )
        if hooks_by_context is None:
            app._row_repaint_hooks.append(repaint)
        else:
            hooks_by_context.setdefault(context, []).append((track.id, repaint))
        state["art_label"] = art
        return row

    @staticmethod
    def update(
        app: MagicMusicPlayerApp,
        row: ctk.CTkFrame,
        track: Track,
        context: str,
        index: int,
        trailing: str | None = None,
    ) -> None:
        """Update a retained row in place when its track or position changes."""
        state = row._mmp_state
        old_track = state["track"]
        old_index = state["index"]
        old_trailing = state["trailing"]
        if old_index != index or getattr(row, "_mmp_hidden", False):
            row.grid(row=index)
            row._mmp_hidden = False
        state["index"] = index
        if old_track == track and old_trailing == trailing:
            return

        state["track"] = track
        state["trailing"] = trailing
        row._mmp_track_id = track.id
        row._mmp_repaint_entry = (track.id, row._mmp_repaint)

        title_label = state["title_label"]
        artist_label = state["artist_label"]
        duration_label = state["duration_label"]
        if title_label is not None:
            title_label.configure(text=table_text(track.title, 64))
        if artist_label is not None:
            if context == "downloads":
                subtitle = ""
            elif context == "search":
                subtitle = table_text(f"{track.artist}  ·  {track.source}", 52)
            else:
                subtitle = table_text(track.artist, 46)
            artist_label.configure(text=subtitle)
        if duration_label is not None:
            side_text = (trailing or "") if context == "downloads" else track.duration_label
            duration_label.configure(text=side_text)

        if old_track.thumbnail_url != track.thumbnail_url:
            art = state["art_label"]
            if art is not None:
                art.configure(image=None, text=app.icons.glyph("music_note"))
                if track.thumbnail_url:
                    app._request_art(track, art, THUMB_DISPLAY_SIZE)
            state["art_url"] = track.thumbnail_url
        heart_button = state["heart_button"]
        if heart_button is not None:
            state["favorite"] = None
        row._mmp_repaint()

    @staticmethod
    def _icon_button(
        app: MagicMusicPlayerApp,
        parent: ctk.CTkFrame,
        glyph_name: str,
        color_val: str,
        command: Callable,
    ) -> ctk.CTkButton:
        text = app.icons.glyph(glyph_name) if app.icons.available() else app._glyph_or(glyph_name)
        button = ctk.CTkButton(
            parent,
            text=text if text else "\u2022",
            width=30,
            height=28,
            corner_radius=7,
            fg_color="transparent",
            hover_color=app.palette.hover,
            text_color=color_val,
            font=app.icons.font(13) if app.icons.available() else ctk.CTkFont(size=13),
            command=command,
        )
        button._mmp_text_color = color_val
        return button
