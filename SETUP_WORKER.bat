@echo off
chcp 65001 >nul
title VE3 - Setup Worker (Image/Video)

:: Use pushd for UNC path support
pushd "%~dp0"

echo ============================================
echo   VE3 TOOL - SETUP MAY AO (WORKER)
echo   Dung cho: run_worker.bat
echo ============================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Python chua duoc cai dat!
    echo         Tai tai: https://www.python.org/downloads/
    echo         Nho tick "Add Python to PATH" khi cai!
    popd
    pause
    exit /b 1
)
echo [OK] Python da cai

:: Install dependencies for worker
echo.
echo [1/2] Cai thu vien co ban...
pip install pyyaml openpyxl requests pillow pyperclip pyautogui websocket-client -q
echo [OK] Thu vien co ban

echo.
echo [2/2] Cai thu vien Chrome automation...
pip install selenium webdriver-manager undetected-chromedriver DrissionPage -q
echo [OK] Chrome automation

:: Check Chrome
echo.
echo [*] Kiem tra Chrome...
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    echo [OK] Chrome da cai
) else if exist "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe" (
    echo [OK] Chrome da cai
) else if exist "%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe" (
    echo [OK] Chrome da cai
) else if exist "%USERPROFILE%\Documents\KP\KP.exe" (
    echo [OK] Chrome Portable (KP) da cai
) else (
    echo [!] Chua tim thay Chrome!
    echo     Cai Chrome hoac copy Chrome Portable vao:
    echo     %USERPROFILE%\Documents\KP\KP.exe
)

echo.
echo ============================================
echo   HOAN TAT SETUP MAY AO!
echo ============================================
echo.
echo   Cac lenh co the chay:
echo   - run_worker.bat   : 1 Chrome (full man hinh)
echo   - run_2worker.bat  : 2 Chrome (chia doi)
echo   - run_3worker.bat  : 3 Chrome (grid)
echo.
echo ============================================

popd
pause
