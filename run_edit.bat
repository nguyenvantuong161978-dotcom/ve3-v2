@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo ============================================================
echo   VE3 TOOL - EDIT MODE (Compose MP4)
echo ============================================================
echo.

REM Check if Python is available
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found!
    pause
    exit /b 1
)

REM Run with arguments or default
if "%~1"=="" (
    python run_edit.py --parallel 2
) else (
    python run_edit.py %*
)

pause
