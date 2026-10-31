# Magic Music Player MMP

Lightweight Python desktop music search, streaming, and download app.

## Search and browsing

- Search results appear as YouTube, YouTube Music, and SoundCloud respond, so the first matches are usable before every source finishes.
- Search rows show their provider, and recent results are reused immediately for repeat searches while fresh results load in the background.
- The app keeps up to five recent search terms between launches; clear them from the Search page.
- Search, Library, Downloads, and Up Next lists stay on screen when you switch tabs and redraw only after their data changes.
- Arabic queries use the logical text entered in the search box, including when recent searches are selected.

## Setup

Requirements:

- Python 3.10+ for a normal development setup, or the local `tools/python` install created for this workspace.
- `ffmpeg` and `mpv`, either on `PATH` or in the bundled `tools/ffmpeg` and `tools/mpv` folders.

Install Python dependencies:

```powershell
.\scripts\setup.ps1
```

For runtime-only installs, use:

```powershell
pip install -r requirements.txt
```

Run:

```powershell
.\scripts\run_app.ps1
```

Run the Phase 1 backend smoke test:

```powershell
.\.venv\Scripts\python.exe .\scripts\phase1_smoke.py
```

For this workspace's local Python install:

```powershell
.\tools\python\python.exe .\scripts\phase1_smoke.py
```

Run tests:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

For this workspace's local Python install:

```powershell
.\scripts\test.ps1
```

## Build Standalone Windows EXE & Package

To build a portable `.exe` package for sharing with friends (without needing Python installed):

```powershell
.\tools\python\python.exe .\scripts\build_exe.py
```

This generates:
- `dist/Magic Music Player/` containing `Magic Music Player.exe` and bundled tools (`ffmpeg`, `libmpv`).
- `dist/Magic-Music-Player-Windows-x64.zip` (standalone archive ready to share).

The app uses `yt-dlp` for text metadata, raw audio stream extraction, and audio downloads. Playback uses `python-mpv` to stream direct audio URLs inside the native app without opening browser players.
