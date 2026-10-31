from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path


if getattr(sys, "frozen", False):
    PROJECT_ROOT = Path(sys.executable).resolve().parent
else:
    PROJECT_ROOT = Path(__file__).resolve().parents[2]


def get_app_dir() -> Path:
    env_dir = os.environ.get("MMP_CONFIG_DIR")
    if env_dir:
        return Path(env_dir)
    return PROJECT_ROOT / ".mmp_config"


def get_config_file() -> Path:
    return get_app_dir() / "settings.json"


APP_DIR = get_app_dir()
CONFIG_FILE = get_config_file()
DEFAULT_DOWNLOAD_DIR = PROJECT_ROOT / "downloads"


@dataclass(slots=True)
class AppConfig:
    download_dir: Path
    audio_format: str = "mp3"
    audio_quality_kbps: int = 192
    volume_normalization: bool = False

    @classmethod
    def load(cls) -> "AppConfig":
        default_dir = DEFAULT_DOWNLOAD_DIR
        config_file = get_config_file()
        if not config_file.exists():
            return cls(download_dir=default_dir)

        try:
            data = json.loads(config_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls(download_dir=default_dir)

        raw_download_dir = Path(data.get("download_dir", default_dir))
        # Protect against test leakage (e.g. pytest temp directory) or removed folders
        if ("pytest" in str(raw_download_dir) or not raw_download_dir.exists()) and default_dir.exists():
            raw_download_dir = default_dir

        return cls(
            download_dir=raw_download_dir,
            audio_format=data.get("audio_format", "mp3"),
            audio_quality_kbps=int(data.get("audio_quality_kbps", 192)),
            volume_normalization=bool(data.get("volume_normalization", False)),
        )

    def save(self) -> None:
        get_app_dir().mkdir(parents=True, exist_ok=True)
        payload = {
            "download_dir": str(self.download_dir),
            "audio_format": self.audio_format,
            "audio_quality_kbps": self.audio_quality_kbps,
            "volume_normalization": self.volume_normalization,
        }
        get_config_file().write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def ensure_download_dir(self) -> Path:
        try:
            self.download_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            self.download_dir = DEFAULT_DOWNLOAD_DIR
            self.download_dir.mkdir(parents=True, exist_ok=True)
        return self.download_dir
