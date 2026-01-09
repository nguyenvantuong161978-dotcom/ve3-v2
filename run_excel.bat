@echo off
chcp 65001 >nul
title VE3 - Voice to Excel (Master)

:: Use pushd for UNC path support (VMware, RDP shared folders)
pushd "%~dp0"

echo ============================================
echo   VE3 TOOL - VOICE TO EXCEL
echo   Tao SRT + Excel tu voice file
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python chua duoc cai dat!
    popd
    pause
    exit /b 1
)

:: Check dependencies
python -c "import yaml" 2>nul
if %errorlevel% neq 0 (
    echo [*] Installing dependencies...
    pip install pyyaml openpyxl requests openai-whisper -q
)

:: Run the script
python run_excel.py %*

if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Co loi xay ra!
)

popd
pause
