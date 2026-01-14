@echo off
chcp 65001 >nul
title VE3 - Switch Branch

:: Use pushd for UNC path support
pushd "%~dp0"

echo ============================================
echo   VE3 TOOL - CHUYEN BRANCH
echo ============================================
echo.

:: Show current branch
set CURRENT=main
if exist "config\current_branch.txt" (
    set /p CURRENT=<config\current_branch.txt
)
echo Branch hien tai: %CURRENT%
echo.

:: Ask for new branch
set /p BRANCH="Nhap branch moi (vd: claude/fix-video-reload-DtCEu): "

if "%BRANCH%"=="" (
    echo [ERROR] Chua nhap ten branch!
    popd
    pause
    exit /b 1
)

echo.
echo [*] Dang chuyen sang: %BRANCH%

:: Save new branch to config
if not exist "config" mkdir config
echo %BRANCH%> config\current_branch.txt

:: Thu update bang git truoc (neu co)
where git >nul 2>&1
if %errorlevel% equ 0 (
    if exist ".git" (
        echo [*] Dang cap nhat bang Git...
        git fetch origin %BRANCH% 2>nul
        git checkout %BRANCH% 2>nul || git checkout -b %BRANCH% origin/%BRANCH% 2>nul
        git reset --hard origin/%BRANCH% 2>nul
        if %errorlevel% equ 0 (
            echo [OK] Da chuyen branch!
            goto :done
        )
    )
)

:: Neu khong co git, dung Python updater
echo [*] Dang tai branch bang Python...
python UPDATE.py %BRANCH%

:done
echo.
echo ============================================
echo   [OK] DA CHUYEN SANG: %BRANCH%
echo ============================================

popd
pause
