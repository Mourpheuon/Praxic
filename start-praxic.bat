@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m praxic --host 127.0.0.1
) else (
  python -m praxic --host 127.0.0.1
)
exit /b %errorlevel%
