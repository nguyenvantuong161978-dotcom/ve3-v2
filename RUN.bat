@echo off
:: VE3 Tool - Auto Update & Run
:: Khong can git - tu dong tai tu GitHub

cd /d "%~dp0"

echo ========================================
echo   VE3 Tool - Browser JS Mode
echo ========================================
echo.

:: Doc branch tu config file
set BRANCH=main
if exist "config\current_branch.txt" (
    set /p BRANCH=<config\current_branch.txt
)

:: Thu update bang git truoc (neu co)
where git >nul 2>&1
if %errorlevel% equ 0 (
    if exist ".git" (
        echo [*] Git found, updating from %BRANCH%...
        git fetch origin %BRANCH% 2>nul
        git reset --hard origin/%BRANCH% 2>nul
        if %errorlevel% equ 0 (
            echo [OK] Updated via git
            goto :run
        )
    )
)

:: Neu khong co git, dung Python updater
echo [*] Checking for updates...
python UPDATE.py 2>nul
if %errorlevel% neq 0 (
    echo [!] Update skipped, using local version
)

:run
echo.
echo [*] Starting VE3 Tool...
echo.

python ve3_pro.py

pause
