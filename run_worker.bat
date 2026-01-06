@echo off
chcp 65001 >nul
title VE3 - Worker (Image/Video)

cd /d "%~dp0"

echo ============================================
echo   VE3 TOOL - WORKER MODE (Image/Video)
echo ============================================
echo.

python run_worker.py %*

pause
