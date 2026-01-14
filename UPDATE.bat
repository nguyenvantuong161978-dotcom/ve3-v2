@echo off
chcp 65001 >nul
title VE3 - Update

:: Use pushd for UNC path support
pushd "%~dp0"

echo ============================================
echo   VE3 TOOL - CAP NHAT
echo ============================================
echo.

:: Doc branch tu config file
set BRANCH=main
if exist "config\current_branch.txt" (
    set /p BRANCH=<config\current_branch.txt
)
echo [*] Branch hien tai: %BRANCH%
echo.

:: Thu update bang git truoc (neu co)
where git >nul 2>&1
if %errorlevel% equ 0 (
    if exist ".git" (
        echo [*] Dang cap nhat bang Git...
        git fetch origin %BRANCH% 2>nul
        git reset --hard origin/%BRANCH% 2>nul
        if %errorlevel% equ 0 (
            echo [OK] Da cap nhat!
            goto :done
        )
    )
)

:: Neu khong co git, dung Python updater
echo [*] Dang cap nhat bang Python...
python UPDATE.py

:done
echo.
echo ============================================
echo   [OK] HOAN TAT!
echo ============================================

popd
pause
