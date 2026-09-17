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
pip install --break-system-packages "fastapi>=0.111.0" "uvicorn[standard]>=0.30.0" "python-multipart>=0.0.9" structlog pydantic python-dotenv httpx openai tiktoken typer rich -q
if errorlevel 1 (
    echo  [ERROR] Dependency installation failed.
    exit /b 1
)

echo  [3/3] Building praxic-backend.exe...
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
echo   Output: dist\praxic-backend.exe
echo   Backend only. See maintenance/RELEASE_DIAGNOSIS.md before distributing.
echo  ==================================================
echo.
pause
