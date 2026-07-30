@echo off
REM ============================================================
REM  Praxic - Build exe
REM ============================================================

echo.
echo  ==================================================
echo   Praxic - Build Tool
echo  ==================================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python not found. Please install Python 3.11+
    pause
    exit /b 1
)

echo  [1/3] Installing PyInstaller...
pip install pyinstaller --break-system-packages -q
if errorlevel 1 (
    echo  [ERROR] Failed to install PyInstaller
    pause
    exit /b 1
)

echo  [2/3] Checking dependencies...
pip install --break-system-packages "fastapi>=0.111.0" "uvicorn[standard]>=0.30.0" structlog pydantic python-dotenv httpx openai tiktoken typer rich -q
if errorlevel 1 (
    echo  [WARN] Some dependencies may have failed, continuing...
)

echo  [3/3] Building 即物穷理.exe...
echo.
pyinstaller praxic.spec --noconfirm --clean

if errorlevel 1 (
    echo.
    echo  [ERROR] Build failed. Check the output above.
    pause
    exit /b 1
)

echo.
echo  ==================================================
echo   Build complete!
echo   Output: dist\即物穷理.exe
echo   Double-click to launch the web interface.
echo  ==================================================
echo.
pause
