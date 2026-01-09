@echo off
chcp 65001 >nul
title VE3 - Worker (Image/Video)

:: Use pushd for UNC path support (VMware, RDP shared folders)
pushd "%~dp0"

echo ============================================
echo   VE3 TOOL - WORKER MODE (Image/Video)
echo ============================================
echo.

python run_worker.py %*

popd
pause
