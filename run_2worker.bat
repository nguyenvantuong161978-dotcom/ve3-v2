@echo off
chcp 65001 >nul
title VE3 - 2 Workers (Split Screen)

:: Use pushd for UNC path support (VMware, RDP shared folders)
pushd "%~dp0"

echo ============================================
echo   VE3 TOOL - 2 WORKERS (SPLIT SCREEN)
echo   Chrome 1: Left half | Chrome 2: Right half
echo ============================================
echo.

:: Start Worker 0 (LEFT) in new window
start "VE3 Worker 0 (LEFT)" cmd /c "python run_worker.py --worker-id 0 --total-workers 2 && pause"

:: Wait 3 seconds before starting second worker
timeout /t 3 /nobreak >nul

:: Start Worker 1 (RIGHT) in new window
start "VE3 Worker 1 (RIGHT)" cmd /c "python run_worker.py --worker-id 1 --total-workers 2 && pause"

echo.
echo [*] Started 2 workers in separate windows
echo [*] Worker 0: LEFT half of screen
echo [*] Worker 1: RIGHT half of screen
echo.
echo Press any key to close this window...

popd
pause
