@echo off
setlocal

cd /d "%~dp0"
"%~dp0tools\python\python.exe" "%~dp0run.py"
pause

