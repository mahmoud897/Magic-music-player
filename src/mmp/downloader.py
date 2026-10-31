from __future__ import annotations

import asyncio
import subprocess
import sys
from dataclasses import dataclass, field
from enum import Enum
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from yt_dlp import YoutubeDL

from .async_bridge import AsyncWorker
from .config import PROJECT_ROOT
from .logging_config import get_logger
from .models import Track

if TYPE_CHECKING:
    from .cache_manager import AudioCacheManager

logger = get_logger("downloader")

ProgressCallback = Callable[["DownloadProgress"], None]


class DownloadStatus(str, Enum):
    QUEUED = "queued"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class DownloadProgress:
    status: str
    percent: float
    speed_label: str
    eta_label: str
    filename: str


@dataclass(slots=True)
class DownloadTask:
    track: Track
    status: DownloadStatus = DownloadStatus.QUEUED
    progress: DownloadProgress = field(
        default_factory=lambda: DownloadProgress("queued", 0.0, "", "", "")
    )
    result_path: Path | None = None
    error: str | None = None


class DownloadService:
    def __init__(
        self,
        output_dir: Path,
        audio_format: str = "mp3",
        quality_kbps: int = 192,
        cache_manager: AudioCacheManager | None = None,
    ) -> None:
        self.output_dir = output_dir
        self.audio_format = audio_format
        self.quality_kbps = quality_kbps
        self.cache_manager = cache_manager

    async def download(
        self, webpage_url: str, progress_callback: ProgressCallback, track: Track | None = None
    ) -> Path:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            partial(self._download_sync, webpage_url, progress_callback, track),
        )

    def _download_sync(
        self, webpage_url: str, progress_callback: ProgressCallback, track: Track | None = None
    ) -> Path:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        final_path: Path | None = None
        bundled_ffmpeg = PROJECT_ROOT / "tools" / "ffmpeg"
        if not bundled_ffmpeg.exists() and hasattr(sys, "_MEIPASS"):
            bundled_ffmpeg = Path(sys._MEIPASS) / "tools" / "ffmpeg"
        if (bundled_ffmpeg / "bin" / "ffmpeg.exe").exists():
            bundled_ffmpeg = bundled_ffmpeg / "bin"

        # Fast path: convert directly from audio cache if track was already streamed or cached
        if track and self.cache_manager and not track.id.startswith("local:"):
            cached_file = self.cache_manager.get_cached_audio(track.id)
            if cached_file and cached_file.is_file():
                safe_title = "".join(c for c in track.title if c.isalnum() or c in " ._- ()[]").strip() or "track"
                out_filename = f"{safe_title[:180]} [{track.id}].{self.audio_format}"
                out_path = self.output_dir / out_filename
                if out_path.is_file() and out_path.stat().st_size > 4096:
                    progress_callback(DownloadProgress("completed", 100.0, "Instant", "", out_filename))
                    return out_path

                progress_callback(DownloadProgress("processing", 50.0, "Cache Instant", "converting", out_filename))
                try:
                    ffmpeg_bin = bundled_ffmpeg / "ffmpeg.exe"
                    ffmpeg_cmd = str(ffmpeg_bin) if ffmpeg_bin.exists() else "ffmpeg"
                    cmd = [
                        ffmpeg_cmd,
                        "-y",
                        "-i",
                        str(cached_file),
                        "-vn",
                        "-b:a",
                        f"{self.quality_kbps}k",
                        str(out_path),
                    ]
                    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                    if out_path.is_file():
                        progress_callback(DownloadProgress("completed", 100.0, "Instant", "", out_filename))
                        return out_path
                except Exception as exc:
                    logger.warning("Cache fast-path conversion failed, falling back to network: %s", exc)

        def hook(data: dict) -> None:
            nonlocal final_path
            filename = data.get("filename") or ""
            if data.get("status") == "finished":
                final_path = Path(filename)
                progress_callback(DownloadProgress("processing", 100.0, "", "finalizing", filename))
                return

            total = data.get("total_bytes") or data.get("total_bytes_estimate") or 0
            downloaded = data.get("downloaded_bytes") or 0
            percent = (downloaded / total * 100) if total else 0.0
            eta = data.get("eta")
            speed = data.get("speed")
            progress_callback(
                DownloadProgress(
                    status=str(data.get("status") or "downloading"),
                    percent=percent,
                    speed_label=self._format_speed(speed),
                    eta_label=self._format_eta(eta),
                    filename=filename,
                )
            )

        options = {
            "quiet": True,
            "no_warnings": True,
            "format": "bestaudio[ext=m4a]/bestaudio[acodec^=opus]/bestaudio/best",
            "outtmpl": str(self.output_dir / "%(title).180B [%(id)s].%(ext)s"),
            "noplaylist": True,
            "progress_hooks": [hook],
            "postprocessors": [
                {
                    "key": "FFmpegExtractAudio",
                    "preferredcodec": self.audio_format,
                    "preferredquality": str(self.quality_kbps),
                },
                {"key": "FFmpegMetadata"},
            ],
        }
        if (bundled_ffmpeg / "ffmpeg.exe").exists():
            options["ffmpeg_location"] = str(bundled_ffmpeg)

        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(webpage_url, download=True)

        requested = info.get("requested_downloads") or []
        res_file: Path | None = None
        if requested and requested[0].get("filepath"):
            res_file = Path(requested[0]["filepath"]).with_suffix(f".{self.audio_format}")
        elif final_path is not None:
            res_file = final_path.with_suffix(f".{self.audio_format}")

        if res_file and res_file.is_file():
            if track and self.cache_manager and not track.id.startswith("local:"):
                try:
                    self.cache_manager.put_file(track.id, res_file)
                except Exception:
                    pass
            return res_file
        return self.output_dir

    @staticmethod
    def _format_eta(seconds: float | int | None) -> str:
        if seconds is None:
            return "--"
        minutes, seconds = divmod(int(seconds), 60)
        return f"{minutes}m {seconds:02d}s" if minutes else f"{seconds}s"

    @staticmethod
    def _format_speed(bytes_per_second: float | int | None) -> str:
        if not bytes_per_second:
            return "--"
        value = float(bytes_per_second)
        for unit in ("B/s", "KB/s", "MB/s"):
            if value < 1024 or unit == "MB/s":
                return f"{value:.1f} {unit}"
            value /= 1024
        return "--"


class DownloadManager:
    """Manages a queue of audio download tasks with concurrency limits."""

    def __init__(
        self,
        service_factory: Callable[[], DownloadService],
        worker: AsyncWorker,
        max_concurrent: int = 2,
    ) -> None:
        self._service_factory = service_factory
        self._worker = worker
        self._max_concurrent = max(1, max_concurrent)
        self._queue: list[DownloadTask] = []
        self._active: dict[str, DownloadTask] = {}
        self._completed: list[DownloadTask] = []
        self._listeners: list[Callable[[DownloadTask], None]] = []

    def add_listener(self, listener: Callable[[DownloadTask], None]) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[DownloadTask], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def _notify(self, task: DownloadTask) -> None:
        for listener in list(self._listeners):
            try:
                listener(task)
            except Exception as exc:
                logger.warning("Error notifying download listener: %s", exc)

    def enqueue(self, track: Track) -> DownloadTask:
        # Check if already queued or active
        for task in self._queue:
            if task.track.id == track.id:
                return task
        if track.id in self._active:
            return self._active[track.id]

        task = DownloadTask(track=track, status=DownloadStatus.QUEUED)
        self._queue.append(task)
        logger.info("Enqueued download for track %s (%s)", track.id, track.title)
        self._notify(task)
        self._process_queue()
        return task

    def get_task(self, track_id: str) -> DownloadTask | None:
        if track_id in self._active:
            return self._active[track_id]
        for task in self._queue:
            if task.track.id == track_id:
                return task
        for task in self._completed:
            if task.track.id == track_id:
                return task
        return None

    def all_tasks(self) -> list[DownloadTask]:
        return list(self._active.values()) + list(self._queue) + list(self._completed)

    def aggregate_stats(self) -> tuple[int, int, float]:
        """Return (active_count, queued_count, overall_percent)."""
        active_count = len(self._active)
        queued_count = len(self._queue)
        if not active_count:
            return 0, queued_count, 0.0
        total_percent = sum(t.progress.percent for t in self._active.values())
        avg_percent = total_percent / active_count
        return active_count, queued_count, avg_percent

    def _process_queue(self) -> None:
        while len(self._active) < self._max_concurrent and self._queue:
            task = self._queue.pop(0)
            task.status = DownloadStatus.DOWNLOADING
            self._active[task.track.id] = task
            self._start_download(task)

    def _start_download(self, task: DownloadTask) -> None:
        logger.info("Starting download for track %s (%s)", task.track.id, task.track.title)
        service = self._service_factory()

        def on_progress(progress: DownloadProgress) -> None:
            task.progress = progress
            if progress.status == "processing":
                task.status = DownloadStatus.PROCESSING
            else:
                task.status = DownloadStatus.DOWNLOADING
            self._notify(task)

        def on_complete(future) -> None:
            try:
                path = future.result()
                task.status = DownloadStatus.COMPLETED
                task.result_path = path
                task.progress = DownloadProgress("completed", 100.0, "", "", path.name)
                logger.info("Download completed: %s", path)
            except Exception as exc:
                task.status = DownloadStatus.FAILED
                task.error = str(exc)
                logger.error("Download failed for %s: %s", task.track.title, exc)

            self._active.pop(task.track.id, None)
            self._completed.append(task)
            self._notify(task)
            self._process_queue()

        import inspect

        try:
            sig = inspect.signature(service.download)
            accepts_track = "track" in sig.parameters or any(
                p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()
            )
        except Exception:
            accepts_track = False

        coro = (
            service.download(task.track.webpage_url, on_progress, track=task.track)
            if accepts_track
            else service.download(task.track.webpage_url, on_progress)
        )
        self._worker.submit(coro, on_complete)
