import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"
BUILD_DIR = ROOT / "build"
APP_NAME = "Magic Music Player"
PACKAGE_DIR = DIST_DIR / APP_NAME
ZIP_NAME = "Magic-Music-Player-Windows-x64.zip"


def clean():
    print(">>> Cleaning previous builds...")
    for p in [BUILD_DIR, DIST_DIR]:
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)


def build_pyinstaller():
    print(">>> Running PyInstaller...")
    python_exe = sys.executable
    icon_path = ROOT / "assets" / "icon.ico"

    cmd = [
        python_exe,
        "-m",
        "PyInstaller",
        "--noconsole",
        "--onedir",
        f"--name={APP_NAME}",
        f"--icon={icon_path}",
        "--paths=src",
        f"--add-data={icon_path};assets",
        "--collect-all=customtkinter",
        "--collect-all=yt_dlp",
        "--collect-all=arabic_reshaper",
        "--collect-all=bidi",
        "--hidden-import=PIL",
        "--hidden-import=PIL.Image",
        "--hidden-import=PIL.ImageTk",
        "--hidden-import=mpv",
        "--hidden-import=sqlite3",
        "--hidden-import=darkdetect",
        "--clean",
        "-y",
        str(ROOT / "run.py"),
    ]

    print("Running command:", " ".join(cmd))
    res = subprocess.run(cmd, cwd=str(ROOT))
    if res.returncode != 0:
        raise RuntimeError(f"PyInstaller failed with exit code {res.returncode}")


def bundle_tools_and_assets():
    print(">>> Bundling tools and dependencies into package...")
    # Bundle FFmpeg
    target_ffmpeg = PACKAGE_DIR / "tools" / "ffmpeg"
    target_ffmpeg.mkdir(parents=True, exist_ok=True)
    src_ffmpeg = ROOT / "tools" / "ffmpeg" / "ffmpeg.exe"
    if src_ffmpeg.exists():
        print(f"Copying FFmpeg from {src_ffmpeg}...")
        shutil.copy2(src_ffmpeg, target_ffmpeg / "ffmpeg.exe")

    # Bundle libmpv
    target_mpv = PACKAGE_DIR / "tools" / "mpv"
    target_mpv.mkdir(parents=True, exist_ok=True)
    src_mpv_dir = ROOT / "tools" / "mpv"
    for dll_name in ["libmpv-2.dll", "d3dcompiler_43.dll"]:
        src_dll = src_mpv_dir / dll_name
        if src_dll.exists():
            print(f"Copying {dll_name}...")
            shutil.copy2(src_dll, target_mpv / dll_name)
            # Also copy to root directory next to .exe for foolproof DLL loading
            shutil.copy2(src_dll, PACKAGE_DIR / dll_name)

    # Create empty downloads folder
    (PACKAGE_DIR / "downloads").mkdir(parents=True, exist_ok=True)

    # Create README for friends
    readme_content = """=================================================
  Magic Music Player (MMP)
=================================================

Thank you for trying Magic Music Player!

HOW TO RUN:
1. Double-click "Magic Music Player.exe" to launch.
2. No Python, no ffmpeg, and no additional software is required.

FEATURES:
- Fast search across YouTube, YouTube Music, and SoundCloud.
- High quality ad-free audio streaming.
- Built-in equalizer and presets.
- Arabic search & display support.
- One-click track downloader (saved in the 'downloads' folder).
- Lightweight & minimal resource usage.

Enjoy listening!
"""
    (PACKAGE_DIR / "README.txt").write_text(readme_content, encoding="utf-8")


def create_zip_archive():
    print(f">>> Creating ZIP archive: {ZIP_NAME}...")
    zip_path = DIST_DIR / ZIP_NAME
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for file_path in PACKAGE_DIR.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(DIST_DIR)
                zf.write(file_path, arcname)

    size_mb = zip_path.stat().st_size / (1024 * 1024)
    print(f"Package created successfully: {zip_path} ({size_mb:.2f} MB)")


def main():
    clean()
    build_pyinstaller()
    bundle_tools_and_assets()
    create_zip_archive()
    print("\n==========================================")
    print(" BUILD & PACKAGING COMPLETE!")
    print(f" Folder: {PACKAGE_DIR}")
    print(f" ZIP:    {DIST_DIR / ZIP_NAME}")
    print("==========================================\n")


if __name__ == "__main__":
    main()
