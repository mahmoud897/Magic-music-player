@echo off
setlocal

cd /d "%~dp0"
start "Magic Music Player" "%~dp0tools\python\pythonw.exe" "%~dp0run.py"

