@echo off
:: ============================================
:: VE3 Tool - SETUP (Cai dat dependencies)
:: ============================================
:: Chay file nay 1 lan khi cai tool len may moi
:: ============================================

cd /d "%~dp0"

echo ========================================
echo   VE3 TOOL - CAI DAT DEPENDENCIES
echo ========================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Chua cai Python!
    echo         Tai tai: https://www.python.org/downloads/
    echo         Nho tick "Add Python to PATH" khi cai!
    echo.
    pause
    exit /b 1
)
echo [OK] Python da cai

:: Check FFmpeg
ffmpeg -version >nul 2>&1
if %errorlevel% neq 0 (
    echo.
    echo [WARN] FFmpeg chua cai! Can cho Voice to SRT
    echo        Tai tai: https://www.gyan.dev/ffmpeg/builds/
    echo        Hoac: winget install ffmpeg
    echo.
) else (
    echo [OK] FFmpeg da cai
)

:: Check VC++ Redistributable
if not exist "%SystemRoot%\System32\vcruntime140.dll" (
    echo.
    echo [WARN] Visual C++ Redistributable chua cai!
    echo        Tai tai: https://aka.ms/vs/17/release/vc_redist.x64.exe
    echo.

    :: Check if vc_redist in tools folder
    if exist "tools\vc_redist.x64.exe" (
        echo [*] Tim thay vc_redist trong tools\, dang cai...
        start /wait tools\vc_redist.x64.exe /install /quiet /norestart
        echo [OK] Da cai VC++ Redistributable
    )
) else (
    echo [OK] VC++ Redistributable da cai
)

echo.
echo ========================================
echo   CAI DAT PYTHON PACKAGES
echo ========================================
echo.

:: Upgrade pip
echo [*] Upgrade pip...
python -m pip install --upgrade pip -q

:: Install requirements
echo [*] Cai dat dependencies (mat vai phut)...
pip install -r requirements.txt

echo.
echo ========================================
echo   KIEM TRA CAI DAT
echo ========================================
echo.

:: Test imports
python -c "import yaml; print('[OK] pyyaml')"
python -c "import PIL; print('[OK] pillow')"
python -c "import selenium; print('[OK] selenium')"
python -c "from DrissionPage import ChromiumPage; print('[OK] DrissionPage')"
python -c "import whisper; print('[OK] whisper')" 2>nul || echo [WARN] whisper can VC++ Redistributable

echo.
echo ========================================
echo   HOAN TAT!
echo ========================================
echo.
echo   Chay RUN.bat de khoi dong tool
echo.
echo ========================================
pause
