@echo off
chcp 65001 >nul
title VE3 - 3 Workers (Grid)

:: Use pushd for UNC path support (VMware, RDP shared folders)
pushd "%~dp0"

echo ============================================
echo   VE3 TOOL - 3 WORKERS (GRID)
echo   Top: Worker 0 (Left) | Worker 1 (Right)
echo   Bottom: Worker 2 (Full width)
echo ============================================
echo.

:: Start Worker 0 (TOP-LEFT)
start "VE3 Worker 0 (TOP-LEFT)" cmd /c "python run_worker.py --worker-id 0 --total-workers 3 && pause"

:: Wait before next
timeout /t 2 /nobreak >nul

:: Start Worker 1 (TOP-RIGHT)
start "VE3 Worker 1 (TOP-RIGHT)" cmd /c "python run_worker.py --worker-id 1 --total-workers 3 && pause"

:: Wait before next
timeout /t 2 /nobreak >nul

:: Start Worker 2 (BOTTOM)
start "VE3 Worker 2 (BOTTOM)" cmd /c "python run_worker.py --worker-id 2 --total-workers 3 && pause"

echo.
echo [*] Started 3 workers in separate windows
echo.
echo Press any key to close this window...

popd
pause
