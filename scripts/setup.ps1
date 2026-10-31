$ErrorActionPreference = "Stop"

if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
    throw "Python 3.10+ was not found on PATH. Install Python, then rerun this script."
}

python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"

Write-Host ""
Write-Host "Setup complete."
Write-Host "Run the app with: .\.venv\Scripts\python.exe run.py"
Write-Host "Make sure ffmpeg and mpv are installed and available on PATH."
