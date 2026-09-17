@echo off
REM Install .[desktop] and pyinstaller in the active environment first.
cd /d "%~dp0"
python scripts\build_desktop.py --backend-only
exit /b %errorlevel%
