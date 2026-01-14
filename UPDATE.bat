@echo off
:: VE3 Tool - Auto Update
:: Khong can git - tu dong tai tu GitHub

chcp 65001 >nul
pushd "%~dp0"

echo ========================================
echo   VE3 Tool - CAP NHAT
echo ========================================
echo.

:: Doc branch tu config file
set BRANCH=main
if exist "config\current_branch.txt" (
    set /p BRANCH=<config\current_branch.txt
)
echo [*] Branch: %BRANCH%

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
if %errorlevel% neq 0 (
    echo [!] Cap nhat that bai, dung ban local
)

:done
echo.
echo ========================================
echo   HOAN TAT!
echo ========================================

popd
pause
