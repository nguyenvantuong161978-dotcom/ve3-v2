@echo off
chcp 65001 >nul
title VE3 - Setup Master (Voice to Excel)

:: Use pushd for UNC path support
pushd "%~dp0"

echo ============================================
echo   VE3 TOOL - SETUP MAY CHU (MASTER)
echo   Dung cho: RUN_MASTER.bat
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

:: Install core dependencies
echo.
echo [1/4] Cai thu vien co ban...
pip install numpy pyyaml openpyxl requests pillow pyperclip gspread google-auth -q

:: Install Whisper (for voice to SRT)
echo.
echo [2/4] Cai Whisper (Voice to SRT)...
echo       (Co the mat 5-10 phut)
pip install openai-whisper -q

:: Install moviepy for video editing
echo.
echo [3/4] Cai MoviePy (Edit video)...
pip install moviepy -q

:: Check/Setup FFmpeg
echo.
echo [4/4] Kiem tra FFmpeg...
where ffmpeg >nul 2>&1
if %errorlevel% neq 0 (
    :: Check if FFmpeg exists in tools folder (with bin subfolder)
    if exist "tools\ffmpeg\bin\ffmpeg.exe" (
        echo [OK] Tim thay FFmpeg trong tools\ffmpeg\bin\
        echo.
        echo [!] Them vao PATH vinh vien...
        setx PATH "%CD%\tools\ffmpeg\bin;%PATH%" >nul 2>&1
        set "PATH=%CD%\tools\ffmpeg\bin;%PATH%"
        echo [OK] Da them vao PATH
    ) else if exist "tools\ffmpeg\ffmpeg.exe" (
        echo [OK] Tim thay FFmpeg trong tools\ffmpeg\
        echo.
        echo [!] Them vao PATH vinh vien...
        setx PATH "%CD%\tools\ffmpeg;%PATH%" >nul 2>&1
        set "PATH=%CD%\tools\ffmpeg;%PATH%"
        echo [OK] Da them vao PATH
    ) else (
        echo [!] Chua co FFmpeg!
        echo.
        echo     Copy vao: tools\ffmpeg\bin\ffmpeg.exe
        echo     Hoac:     tools\ffmpeg\ffmpeg.exe
        echo.
        echo     Tai tu: https://www.gyan.dev/ffmpeg/builds/
        echo.
        echo     Sau do chay lai SETUP_MASTER.bat
    )
) else (
    echo [OK] FFmpeg da co trong PATH
)

echo.
echo ============================================
echo   HOAN TAT SETUP MAY CHU!
echo ============================================
echo.
echo   Cac lenh co the chay:
echo   - RUN_MASTER.bat : Chay run_srt.py + run_edit.py
echo.
echo ============================================

popd
pause
