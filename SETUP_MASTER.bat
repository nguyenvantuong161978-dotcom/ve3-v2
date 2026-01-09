@echo off
chcp 65001 >nul
title VE3 - Setup Master (Voice to Excel)

:: Use pushd for UNC path support
pushd "%~dp0"

echo ============================================
echo   VE3 TOOL - SETUP MAY CHU (MASTER)
echo   Dung cho: run_excel.bat, run_edit.bat
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
echo [1/3] Cai thu vien co ban...
pip install pyyaml openpyxl requests pillow pyperclip -q

:: Install Whisper (for voice to SRT)
echo.
echo [2/3] Cai Whisper (Voice to SRT)...
echo       (Co the mat 5-10 phut)
pip install openai-whisper -q

:: Check/Install FFmpeg
echo.
echo [3/3] Kiem tra FFmpeg...
where ffmpeg >nul 2>&1
if %errorlevel% neq 0 (
    echo [!] FFmpeg chua cai - Dang tai...

    :: Create tools folder
    if not exist "tools\ffmpeg" mkdir "tools\ffmpeg"

    :: Download FFmpeg
    echo     Dang tai FFmpeg...
    curl -L -o "tools\ffmpeg.zip" "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

    if exist "tools\ffmpeg.zip" (
        echo     Dang giai nen...
        powershell -command "Expand-Archive -Path 'tools\ffmpeg.zip' -DestinationPath 'tools\ffmpeg' -Force"
        del "tools\ffmpeg.zip"

        :: Find and move ffmpeg.exe to tools/ffmpeg/
        for /d %%i in (tools\ffmpeg\ffmpeg-*) do (
            move "%%i\bin\ffmpeg.exe" "tools\ffmpeg\" >nul 2>&1
            move "%%i\bin\ffprobe.exe" "tools\ffmpeg\" >nul 2>&1
            rmdir /s /q "%%i" 2>nul
        )

        :: Add to PATH for this session
        set "PATH=%CD%\tools\ffmpeg;%PATH%"
        echo [OK] FFmpeg da cai vao tools\ffmpeg\
        echo.
        echo [!] QUAN TRONG: Them duong dan sau vao PATH:
        echo     %CD%\tools\ffmpeg
    ) else (
        echo [!] Khong tai duoc FFmpeg tu dong
        echo     Tai thu cong: https://www.gyan.dev/ffmpeg/builds/
        echo     Giai nen vao: tools\ffmpeg\
    )
) else (
    echo [OK] FFmpeg da co san
)

echo.
echo ============================================
echo   HOAN TAT SETUP MAY CHU!
echo ============================================
echo.
echo   Cac lenh co the chay:
echo   - run_excel.bat  : Tao Excel tu voice
echo   - run_edit.bat   : Ghep video MP4
echo.
echo ============================================

popd
pause
