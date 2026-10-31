from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from typing import TYPE_CHECKING

import customtkinter as ctk

from ...player import EQ_MIN_GAIN, EQ_PRESETS, normalize_eq_gains
from ...theme import accent_names

if TYPE_CHECKING:
    from ...app import MagicMusicPlayerApp

EQ_FREQ_LABELS = ("31", "62", "125", "250", "500", "1k", "2k", "4k", "8k", "16k")


class SettingsDialog:
    """Toplevel modal dialog for MMP configuration."""

    @classmethod
    def show(cls, app: MagicMusicPlayerApp) -> None:
        dialog = ctk.CTkToplevel(app)
        dialog.title("Settings")
        dialog.geometry("620x640")
        dialog.transient(app)
        dialog.grab_set()
        dialog.grid_columnconfigure(1, weight=1)
        dialog.configure(fg_color=app.palette.surface)

        themed_elements: list[tuple[object, dict[str, str]]] = []

        def register_themed(widget: object, **mapping: str) -> object:
            themed_elements.append((widget, mapping))
            return widget

        def update_dialog_palette() -> None:
            pal = app.palette
            dialog.configure(fg_color=pal.surface)
            for widget, mapping in themed_elements:
                try:
                    if not getattr(widget, "winfo_exists", lambda: True)():
                        continue
                except Exception:
                    continue
                opts = {}
                for opt, token in mapping.items():
                    val = getattr(pal, token, None)
                    if val is not None:
                        opts[opt] = val
                if opts:
                    try:
                        widget.configure(**opts)
                    except Exception:
                        pass

        appearance_var = tk.StringVar(value=app.appearance.capitalize())
        accent_var = tk.StringVar(value=app.accent_name)
        download_dir_var = tk.StringVar(value=str(app.config_model.download_dir))
        format_var = tk.StringVar(value=app.config_model.audio_format)
        quality_var = tk.StringVar(value=str(app.config_model.audio_quality_kbps))

        section_font = ctk.CTkFont(size=14, weight="bold")

        # Appearance section
        lbl_app = register_themed(
            ctk.CTkLabel(dialog, text="Appearance", anchor="w", font=section_font, text_color=app.palette.text),
            text_color="text",
        )
        lbl_app.grid(row=0, column=0, padx=18, pady=(20, 4), sticky="w")

        appearance_menu = register_themed(
            ctk.CTkOptionMenu(
                dialog,
                values=["Dark", "Light"],
                variable=appearance_var,
                fg_color=app.palette.idle,
                button_color=app.palette.accent,
                button_hover_color=app.palette.accent_hover,
                text_color=app.palette.text,
            ),
            fg_color="idle",
            button_color="accent",
            button_hover_color="accent_hover",
            text_color="text",
        )
        appearance_menu.grid(row=1, column=1, padx=(0, 18), pady=4, sticky="w")

        lbl_acc = register_themed(
            ctk.CTkLabel(dialog, text="Accent color", anchor="w", text_color=app.palette.text),
            text_color="text",
        )
        lbl_acc.grid(row=2, column=0, padx=18, pady=4, sticky="w")

        accent_menu = register_themed(
            ctk.CTkOptionMenu(
                dialog,
                values=list(accent_names()),
                variable=accent_var,
                fg_color=app.palette.idle,
                button_color=app.palette.accent,
                button_hover_color=app.palette.accent_hover,
                text_color=app.palette.text,
            ),
            fg_color="idle",
            button_color="accent",
            button_hover_color="accent_hover",
            text_color="text",
        )
        accent_menu.grid(row=3, column=1, padx=(0, 18), pady=4, sticky="w")

        def preview_theme(*_args) -> None:
            app.appearance = appearance_var.get().lower()
            app.accent_name = accent_var.get()
            app.library.set_setting("appearance", app.appearance)
            app.library.set_setting("accent", app.accent_name)
            app._apply_theme()
            update_dialog_palette()

        appearance_menu.configure(command=preview_theme)
        accent_menu.configure(command=preview_theme)

        # Downloads section
        lbl_dl = register_themed(
            ctk.CTkLabel(dialog, text="Downloads", anchor="w", font=section_font, text_color=app.palette.text),
            text_color="text",
        )
        lbl_dl.grid(row=4, column=0, padx=18, pady=(16, 4), sticky="w")

        lbl_folder = register_themed(
            ctk.CTkLabel(dialog, text="Folder", anchor="w", text_color=app.palette.text),
            text_color="text",
        )
        lbl_folder.grid(row=5, column=0, padx=18, pady=4, sticky="w")
        entry_dl = register_themed(
            ctk.CTkEntry(
                dialog,
                textvariable=download_dir_var,
                fg_color=app.palette.surface_alt,
                text_color=app.palette.text,
                border_color=app.palette.idle,
            ),
            fg_color="surface_alt",
            text_color="text",
            border_color="idle",
        )
        entry_dl.grid(row=5, column=1, padx=(0, 8), pady=4, sticky="ew")

        def pick_dir() -> None:
            selected = filedialog.askdirectory(initialdir=download_dir_var.get())
            if selected:
                download_dir_var.set(selected)

        browse_button = register_themed(
            ctk.CTkButton(
                dialog,
                text="Browse",
                width=90,
                command=pick_dir,
                fg_color=app.palette.idle,
                hover_color=app.palette.idle_hover,
                text_color=app.palette.text,
            ),
            fg_color="idle",
            hover_color="idle_hover",
            text_color="text",
        )
        browse_button.grid(row=5, column=2, padx=(0, 18), pady=4)

        lbl_fmt = register_themed(
            ctk.CTkLabel(dialog, text="Format", anchor="w", text_color=app.palette.text),
            text_color="text",
        )
        lbl_fmt.grid(row=6, column=0, padx=18, pady=4, sticky="w")

        menu_fmt = register_themed(
            ctk.CTkOptionMenu(
                dialog,
                values=["mp3", "m4a"],
                variable=format_var,
                fg_color=app.palette.idle,
                button_color=app.palette.accent,
                button_hover_color=app.palette.accent_hover,
                text_color=app.palette.text,
            ),
            fg_color="idle",
            button_color="accent",
            button_hover_color="accent_hover",
            text_color="text",
        )
        menu_fmt.grid(row=6, column=1, padx=(0, 18), pady=4, sticky="w")

        lbl_bit = register_themed(
            ctk.CTkLabel(dialog, text="Bitrate", anchor="w", text_color=app.palette.text),
            text_color="text",
        )
        lbl_bit.grid(row=7, column=0, padx=18, pady=4, sticky="w")

        menu_bit = register_themed(
            ctk.CTkOptionMenu(
                dialog,
                values=["128", "192", "256"],
                variable=quality_var,
                fg_color=app.palette.idle,
                button_color=app.palette.accent,
                button_hover_color=app.palette.accent_hover,
                text_color=app.palette.text,
            ),
            fg_color="idle",
            button_color="accent",
            button_hover_color="accent_hover",
            text_color="text",
        )
        menu_bit.grid(row=7, column=1, padx=(0, 18), pady=4, sticky="w")

        # Audio Normalization
        lbl_norm = register_themed(
            ctk.CTkLabel(dialog, text="Normalization", anchor="w", text_color=app.palette.text),
            text_color="text",
        )
        lbl_norm.grid(row=8, column=0, padx=18, pady=4, sticky="w")

        norm_var = tk.BooleanVar(value=bool(getattr(app.config_model, "volume_normalization", False)))
        norm_switch = register_themed(
            ctk.CTkSwitch(
                dialog,
                text="Auto volume (dynaudnorm)",
                variable=norm_var,
                progress_color=app.palette.accent,
                button_color=app.palette.accent,
                button_hover_color=app.palette.accent_hover,
                text_color=app.palette.text,
            ),
            progress_color="accent",
            button_color="accent",
            button_hover_color="accent_hover",
            text_color="text",
        )
        norm_switch.grid(row=8, column=1, padx=(0, 18), pady=4, sticky="w")

        # Equalizer section
        lbl_eq = register_themed(
            ctk.CTkLabel(dialog, text="Equalizer", anchor="w", font=section_font, text_color=app.palette.text),
            text_color="text",
        )
        lbl_eq.grid(row=9, column=0, padx=18, pady=(16, 4), sticky="w")

        eq_preset_var = tk.StringVar(value=app.library.get_setting("eq_preset", "Flat"))
        preset_values = [*EQ_PRESETS.keys(), "Custom"]
        if eq_preset_var.get() not in preset_values:
            eq_preset_var.set("Custom")

        preset_row = ctk.CTkFrame(dialog, fg_color="transparent")
        preset_row.grid(row=10, column=0, columnspan=3, sticky="ew", padx=18, pady=(0, 8))
        lbl_preset = register_themed(
            ctk.CTkLabel(preset_row, text="Preset", anchor="w", text_color=app.palette.text),
            text_color="text",
        )
        lbl_preset.pack(side="left")
        eq_sliders: list[ctk.CTkSlider] = []

        def apply_preset(choice: str) -> None:
            gains = EQ_PRESETS.get(choice)
            if gains is None:
                return
            for slider, gain in zip(eq_sliders, gains):
                slider.set(gain)
            app.active_eq_gains = normalize_eq_gains(gains)
            app.player.set_equalizer(gains)

        def on_slider_changed(_value: float) -> None:
            gains = [float(slider.get()) for slider in eq_sliders]
            app.active_eq_gains = normalize_eq_gains(gains)
            app.player.set_equalizer(gains)
            if eq_preset_var.get() != "Custom":
                eq_preset_var.set("Custom")

        preset_menu = register_themed(
            ctk.CTkOptionMenu(
                preset_row,
                values=preset_values,
                variable=eq_preset_var,
                command=lambda choice: (eq_preset_var.set(choice), apply_preset(choice)),
                fg_color=app.palette.idle,
                button_color=app.palette.accent,
                button_hover_color=app.palette.accent_hover,
                text_color=app.palette.text,
            ),
            fg_color="idle",
            button_color="accent",
            button_hover_color="accent_hover",
            text_color="text",
        )
        preset_menu.pack(side="left", padx=(10, 0))

        bands_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        bands_frame.grid(row=11, column=0, columnspan=3, sticky="ew", padx=18, pady=(0, 6))
        for band_index, freq_label in enumerate(EQ_FREQ_LABELS):
            band = ctk.CTkFrame(bands_frame, fg_color="transparent")
            band.grid(row=0, column=band_index, padx=4, sticky="n")
            slider = register_themed(
                ctk.CTkSlider(
                    band,
                    orientation="vertical",
                    height=120,
                    from_=EQ_MIN_GAIN,
                    to=12.0,
                    number_of_steps=48,
                    command=on_slider_changed,
                    progress_color=app.palette.accent,
                    button_color=app.palette.accent,
                    button_hover_color=app.palette.accent_hover,
                ),
                progress_color="accent",
                button_color="accent",
                button_hover_color="accent_hover",
            )
            slider.set(app.active_eq_gains[band_index] if band_index < len(app.active_eq_gains) else 0.0)
            slider.grid(row=0, column=0)
            lbl_f = register_themed(
                ctk.CTkLabel(band, text=freq_label, font=ctk.CTkFont(size=10), text_color=app.palette.muted),
                text_color="muted",
            )
            lbl_f.grid(row=1, column=0, pady=(4, 0))
            eq_sliders.append(slider)

        def save_and_close() -> None:
            app.config_model.download_dir = Path(download_dir_var.get()).expanduser()
            app.config_model.audio_format = format_var.get()
            app.config_model.audio_quality_kbps = int(quality_var.get())
            app.config_model.volume_normalization = bool(norm_var.get())
            app.config_model.save()
            app.config_model.ensure_download_dir()
            app.downloads_view.invalidate()
            app.player.set_volume_normalization(app.config_model.volume_normalization)

            gains = [float(slider.get()) for slider in eq_sliders]
            app.active_eq_gains = normalize_eq_gains(gains)
            app.library.set_setting("eq_preset", eq_preset_var.get())
            app.library.set_setting("eq_gains", ",".join(f"{gain:.1f}" for gain in app.active_eq_gains))

            app.toast("Settings saved.")
            dialog.destroy()

        save_button = register_themed(
            ctk.CTkButton(
                dialog,
                text="Save",
                width=96,
                height=36,
                corner_radius=18,
                font=ctk.CTkFont(size=13, weight="bold"),
                fg_color=app.palette.accent,
                hover_color=app.palette.accent_hover,
                text_color="#ffffff",
                command=save_and_close,
            ),
            fg_color="accent",
            hover_color="accent_hover",
        )
        save_button.grid(row=11, column=2, padx=(0, 18), pady=(18, 18), sticky="e")

        cancel_button = register_themed(
            ctk.CTkButton(
                dialog,
                text="Cancel",
                width=96,
                height=36,
                corner_radius=18,
                fg_color=app.palette.idle,
                hover_color=app.palette.idle_hover,
                text_color=app.palette.text,
                command=dialog.destroy,
            ),
            fg_color="idle",
            hover_color="idle_hover",
            text_color="text",
        )
        cancel_button.grid(row=11, column=1, padx=(0, 8), pady=(18, 18), sticky="e")
