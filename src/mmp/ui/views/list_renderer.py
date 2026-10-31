from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Hashable

import customtkinter as ctk

from ...models import Track
from ..components.track_row import TrackRow

if TYPE_CHECKING:
    from ...app import MagicMusicPlayerApp


@dataclass(frozen=True, slots=True)
class RenderedTrack:
    key: Hashable
    track: Track
    trailing: str | None = None


class TrackListRenderer:
    """Retain list rows and reconcile changed lists in bounded UI batches."""

    FIRST_BATCH_SIZE = 8
    BATCH_SIZE = 32

    def __init__(
        self,
        app: MagicMusicPlayerApp,
        frame: ctk.CTkFrame,
        context: str,
        on_loading: Callable[[bool], None] | None = None,
    ) -> None:
        self.app = app
        self.frame = frame
        self.context = context
        self.on_loading = on_loading
        self.rows: dict[Hashable, ctk.CTkFrame] = {}
        self._empty_label: ctk.CTkLabel | None = None
        self._empty_message: str | None = None
        self._render_generation = 0
        self._batches_completed = 0
        self._after_id: str | None = None
        self._pending_items: list[RenderedTrack] = []
        self._pending_index = 0
        self._target_indices: dict[Hashable, int] = {}
        self._target_keys: list[Hashable] = []
        self._stale_keys: list[Hashable] = []
        self._empty_message_pending: str | None = None
        self._current_order: list[Hashable] = []
        self._active_scroll_key: Hashable = "default"
        self._scroll_positions: dict[Hashable, float] = {"default": 0.0}
        self._restore_position = 0.0
        self._is_loading = False

    def render(
        self,
        items: list[RenderedTrack],
        empty_message: str,
        *,
        scroll_key: Hashable = "default",
    ) -> None:
        self._save_scroll_position()
        self._restore_position = self._scroll_positions.get(scroll_key, 0.0)
        self._active_scroll_key = scroll_key
        self._render_generation += 1
        generation = self._render_generation
        self._cancel_batch()

        snapshot = list(items)
        if self._matches(snapshot, empty_message):
            self._replace_hooks(snapshot)
            self._set_loading(False)
            self.app.after_idle(self._restore_scroll_position)
            return

        self._target_keys = [item.key for item in snapshot]
        target_key_set = set(self._target_keys)
        self._target_indices = {item.key: index for index, item in enumerate(snapshot)}
        self._pending_items = [
            item for index, item in enumerate(snapshot) if not self._row_matches(item, index)
        ]
        self._pending_index = 0
        self._batches_completed = 0
        self._stale_keys = [key for key in self.rows if key not in target_key_set]
        self._empty_message_pending = empty_message if not snapshot else None
        if snapshot:
            self._clear_empty()

        self._replace_hooks(snapshot)
        is_loading = bool(snapshot or self._stale_keys)
        self._set_loading(is_loading)

        if not snapshot and not self._stale_keys:
            self._show_empty(empty_message)
            self._finish_render(generation)
            return

        # Start after the current event handler returns so the new tab can paint
        # and receive input before any row construction or stale-row removal.
        self._after_id = self.app.after(1, lambda gen=generation: self._process_batch(gen))

    def _matches(self, items: list[RenderedTrack], empty_message: str) -> bool:
        if self._after_id is not None:
            return False
        if not items:
            return not self.rows and self._empty_label is not None and self._empty_message == empty_message
        if [item.key for item in items] != self._current_order or len(items) != len(self.rows):
            return False
        for index, item in enumerate(items):
            if not self._row_matches(item, index):
                return False
        return True

    def _row_matches(self, item: RenderedTrack, index: int) -> bool:
        row = self.rows.get(item.key)
        if row is None or getattr(row, "_mmp_hidden", False):
            return False
        state = getattr(row, "_mmp_state", {})
        return (
            state.get("track") == item.track
            and state.get("trailing") == item.trailing
            and state.get("index") == index
        )

    def _replace_hooks(self, items: list[RenderedTrack]) -> None:
        hooks = getattr(self.app, "_row_repaint_hooks_by_context", {}).get(self.context)
        if hooks is None:
            return
        hooks.clear()
        for item in items:
            row = self.rows.get(item.key)
            entry = getattr(row, "_mmp_repaint_entry", None) if row is not None else None
            if entry is not None:
                hooks.append(entry)

    def _show_empty(self, message: str) -> None:
        if self._empty_label is not None and self._empty_message == message:
            return
        self._clear_empty()
        self._empty_message = message
        self._empty_label = ctk.CTkLabel(
            self.frame,
            text=message,
            font=ctk.CTkFont(size=13),
            text_color=self.app.palette.muted,
            justify="center",
        )
        self.app._themed(self._empty_label, text_color="muted")
        self._empty_label.grid(row=0, column=0, sticky="nsew", pady=60)

    def _clear_empty(self) -> None:
        if self._empty_label is not None:
            try:
                self._empty_label.destroy()
            except Exception:
                pass
        self._empty_label = None
        self._empty_message = None

    def _process_batch(self, generation: int) -> None:
        if generation != self._render_generation:
            return

        batch_size = self.FIRST_BATCH_SIZE if self._batches_completed == 0 else self.BATCH_SIZE
        for key in self._stale_keys[:batch_size]:
            row = self.rows.pop(key, None)
            if row is not None:
                try:
                    row.destroy()
                except Exception:
                    pass
        self._stale_keys = self._stale_keys[batch_size:]

        stop = min(self._pending_index + batch_size, len(self._pending_items))
        for item in self._pending_items[self._pending_index:stop]:
            index = self._target_indices[item.key]
            row = self.rows.get(item.key)
            if row is None:
                self.rows[item.key] = TrackRow.create(
                    self.app,
                    self.frame,
                    item.track,
                    context=self.context,
                    index=index,
                    trailing=item.trailing,
                )
            else:
                row._mmp_update(item.track, index, item.trailing)
        self._pending_index = stop
        self._batches_completed += 1

        if self._pending_index < len(self._pending_items) or self._stale_keys:
            self._after_id = self.app.after(1, lambda gen=generation: self._process_batch(gen))
            return

        if self._empty_message_pending is not None:
            self._show_empty(self._empty_message_pending)
        self._finish_render(generation)

    def _finish_render(self, generation: int) -> None:
        if generation != self._render_generation:
            return
        self._after_id = None
        self._pending_items = []
        self._pending_index = 0
        self._stale_keys = []
        self._current_order = list(self._target_keys)
        self._scroll_positions[self._active_scroll_key] = self._restore_position
        self._set_loading(False)
        self.app.after_idle(self._restore_scroll_position)

    def _set_loading(self, loading: bool) -> None:
        if self._is_loading == loading:
            return
        self._is_loading = loading
        if self.on_loading is not None:
            try:
                self.on_loading(loading)
            except Exception:
                pass

    def _save_scroll_position(self) -> None:
        canvas = getattr(self.frame, "_parent_canvas", None)
        if canvas is None:
            return
        try:
            view = canvas.yview()
            if view:
                self._scroll_positions[self._active_scroll_key] = max(0.0, min(1.0, float(view[0])))
        except Exception:
            pass

    def _restore_scroll_position(self) -> None:
        canvas = getattr(self.frame, "_parent_canvas", None)
        if canvas is not None:
            try:
                canvas.yview_moveto(self._restore_position)
            except Exception:
                pass

    def _cancel_batch(self) -> None:
        if self._after_id is not None:
            try:
                self.app.after_cancel(self._after_id)
            except Exception:
                pass
            self._after_id = None
