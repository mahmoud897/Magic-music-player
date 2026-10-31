@echo off
setlocal

cd /d "%~dp0"
echo ==============================================
echo Building Magic Music Player .exe and Package...
echo ==============================================
"%~dp0tools\python\python.exe" "%~dp0scripts\build_exe.py"
pause
