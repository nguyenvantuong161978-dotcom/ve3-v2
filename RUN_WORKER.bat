@echo off
echo ============================================================
echo   VE3 TOOL - WORKER (VM)
echo ============================================================
echo   Chay run_worker.py:
echo   1. Tao Excel tu SRT (API)
echo   2. Tao anh (characters, locations, scenes)
echo   3. Tao video
echo   4. Sync ve master
echo ============================================================
echo.

REM Kiem tra Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python khong tim thay!
    pause
    exit /b 1
)

REM Chay run_worker.py
echo [WORKER] Starting run_worker.py...
python run_worker.py

echo.
echo ============================================================
echo   WORKER FINISHED!
echo ============================================================
pause
