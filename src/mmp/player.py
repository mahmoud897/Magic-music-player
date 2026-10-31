from __future__ import annotations

import time
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from .config import PROJECT_ROOT
from .logging_config import get_logger

logger = get_logger("player")


EQ_MIN_GAIN = -12.0
EQ_MAX_GAIN = 12.0
EQ_BAND_COUNT = 10
EQ_BAND_FREQUENCIES_HZ = (31, 62, 125, 250, 500, 1000, 2000, 4000, 8000, 16000)

# Media hosts (e.g. YouTube) reject requests carrying libmpv's default agent.
FALLBACK_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)

EQ_PRESETS: dict[str, tuple[float, ...]] = {
    "Flat": (0.0,) * EQ_BAND_COUNT,
    "Bass Boost": (6.0, 5.0, 3.5, 1.5, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0),
    "Treble": (0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.5, 3.0, 4.5, 5.5),
    "Vocal": (-2.0, -1.5, 0.0, 2.5, 4.0, 4.0, 2.5, 0.0, -1.0, -2.0),
    "Rock": (4.5, 3.5, 1.5, -1.0, -2.0, 1.0, 3.0, 4.5, 4.5, 4.0),
    "Electronic": (5.0, 4.5, 1.5, 0.0, -1.5, 1.5, 1.0, 2.5, 4.0, 4.5),
}


def normalize_eq_gains(gains: Iterable[float]) -> list[float]:
    """Clamp to [-12, +12] dB, coerce bad values to 0, pad/truncate to 10 bands."""
    result: list[float] = []
    for gain in list(gains)[:EQ_BAND_COUNT]:
        try:
            value = float(gain)
        except (TypeError, ValueError):
            value = 0.0
        if value != value:  # NaN guard
            value = 0.0
        result.append(round(max(EQ_MIN_GAIN, min(EQ_MAX_GAIN, value)), 1))
    while len(result) < EQ_BAND_COUNT:
        result.append(0.0)
    return result


def build_equalizer_af(gains: Iterable[float]) -> str:
    """Build an mpv lavfi filter graph: one peaking EQ per band.

    Note: the legacy `equalizer=g0:g1:...` filter hangs first playback in the
    bundled libmpv when set while idle; the lavfi graph is reliable.
    """
    normalized = normalize_eq_gains(gains)
    graph = ",".join(
        f"equalizer=f={freq}:t=q:w=1:g={gain:g}"
        for freq, gain in zip(EQ_BAND_FREQUENCIES_HZ, normalized)
    )
    return f"lavfi=[{graph}]"


@dataclass(slots=True)
class PlaybackState:
    paused: bool = True
    position: float = 0.0
    duration: float = 0.0
    volume: int = 70
    loop_enabled: bool = False


class AudioPlayer:
    def __init__(
        self,
        on_track_end: Callable[[], None] | None = None,
        on_track_error: Callable[[str], None] | None = None,
    ) -> None:
        bundled_mpv = PROJECT_ROOT / "tools" / "mpv"
        if not bundled_mpv.exists() and hasattr(sys, "_MEIPASS"):
            bundled_mpv = Path(sys._MEIPASS) / "tools" / "mpv"
        if bundled_mpv.exists():
            os.environ["PATH"] = str(bundled_mpv) + os.pathsep + os.environ.get("PATH", "")
            if hasattr(os, "add_dll_directory"):
                try:
                    os.add_dll_directory(str(bundled_mpv))
                except Exception:
                    pass
        try:
            import mpv
        except ImportError as exc:
            raise RuntimeError(
                "python-mpv is not installed. Install dependencies with `pip install -r requirements.txt`."
            ) from exc

        self.on_track_end = on_track_end
        self.on_track_error = on_track_error
        self._mpv = mpv.MPV(
            ytdl=False,
            video=False,
            osc=False,
            input_default_bindings=False,
            input_vo_keyboard=False,
            demuxer_max_bytes=32 * 1024 * 1024,
            demuxer_readahead_secs=30,
            force_seekable=True,
        )
        self._mpv.volume = 70
        self._loop_enabled = False
        self._volume_normalization = False
        self._eq_gains: list[float] | None = None
        self._last_seek_at = 0.0
        self._mpv.event_callback("end-file")(self._on_mpv_end_file)

    def _on_mpv_end_file(self, event: object) -> None:
        """Runs on mpv's internal thread; fires for clean end-of-file or error."""
        reason_raw = None
        error_msg = ""
        try:
            data = getattr(event, "data", None)
            if data is not None:
                reason_raw = getattr(data, "reason", None)
                error_msg = getattr(data, "error", "")
            if reason_raw is None and hasattr(event, "as_dict"):
                d = event.as_dict()
                reason_raw = d.get("reason")
                error_msg = d.get("error", "")
        except Exception:
            reason_raw = None
            error_msg = ""

        # Normalize reason: could be integer 0 (EOF) or 4 (error), or bytes/string like b'eof'
        is_eof = False
        is_error = False
        if reason_raw is not None:
            if isinstance(reason_raw, (int, float)):
                is_eof = int(reason_raw) == 0
                is_error = int(reason_raw) == 4
            else:
                s = str(reason_raw).lower()
                is_eof = "eof" in s or s == "0"
                is_error = "error" in s or s == "4"

        if is_eof:
            callback = self.on_track_end
            if callback is not None:
                try:
                    callback()
                except Exception as exc:
                    logger.warning("Error in on_track_end callback: %s", exc)
        elif is_error:
            logger.warning("Playback ended with error: %s", error_msg)
            callback_err = self.on_track_error
            if callback_err is not None:
                try:
                    callback_err(str(error_msg or "Playback stream error"))
                except Exception as exc:
                    logger.warning("Error in on_track_error callback: %s", exc)

    def play(self, stream_url: str, http_headers: dict[str, str] | None = None) -> None:
        headers = {key.lower(): value for key, value in (http_headers or {}).items()}
        self._mpv.user_agent = headers.get("user-agent") or FALLBACK_USER_AGENT
        self._mpv.referrer = headers.get("referer", "")
        cookie = headers.get("cookie")
        self._mpv.http_header_fields = f"Cookie: {cookie}" if cookie else ""
        self._mpv.play(stream_url)
        self._mpv.pause = False

    def toggle_pause(self) -> bool:
        self._mpv.pause = not bool(self._mpv.pause)
        return bool(self._mpv.pause)

    def stop(self) -> None:
        self._mpv.stop()

    def seek_absolute(self, seconds: float) -> None:
        now = time.monotonic()
        if now - self._last_seek_at < 0.15:
            return
        self._last_seek_at = now
        self._mpv.seek(max(0.0, seconds), reference="absolute")

    def set_volume(self, volume: int) -> None:
        self._mpv.volume = max(0, min(100, int(volume)))

    def set_loop(self, enabled: bool) -> None:
        self._loop_enabled = enabled
        # Keep mpv's internal loop_file at "no" so mpv cleanly fires EOF events,
        # allowing MMP's application-level queue lifecycle to handle repeats.
        self._mpv.loop_file = "no"

    def _update_af(self) -> None:
        filters: list[str] = []
        if self._eq_gains is not None:
            filters.append(build_equalizer_af(self._eq_gains))
        if self._volume_normalization:
            filters.append("lavfi=[dynaudnorm]")
        self._mpv.af = ",".join(filters) if filters else ""

    def set_volume_normalization(self, enabled: bool) -> None:
        self._volume_normalization = bool(enabled)
        self._update_af()

    def set_equalizer(self, gains: Iterable[float]) -> None:
        self._eq_gains = normalize_eq_gains(gains)
        self._update_af()

    def clear_equalizer(self) -> None:
        self._eq_gains = None
        self._update_af()

    def state(self) -> PlaybackState:
        return PlaybackState(
            paused=bool(self._mpv.pause),
            position=float(self._mpv.time_pos or 0.0),
            duration=float(self._mpv.duration or 0.0),
            volume=int(self._mpv.volume or 0),
            loop_enabled=self._loop_enabled,
        )

    def shutdown(self) -> None:
        """Safely stop and terminate mpv instance."""
        try:
            self._mpv.stop()
        except Exception:
            pass
        try:
            self._mpv.quit()
        except Exception:
            pass
        try:
            self._mpv.terminate()
        except Exception as exc:
            logger.debug("Error terminating mpv: %s", exc)

