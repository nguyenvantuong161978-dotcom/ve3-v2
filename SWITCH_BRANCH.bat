@echo off
:: VE3 Tool - Switch Branch
chcp 65001 >nul
pushd "%~dp0"

echo ========================================
echo   VE3 Tool - DOI BRANCH
echo ========================================
echo.

:: Show current
set CURRENT=main
if exist "config\current_branch.txt" (
    set /p CURRENT=<config\current_branch.txt
)
echo Branch hien tai: %CURRENT%
echo.

:: Ask for new branch
set /p BRANCH="Nhap branch moi: "

if "%BRANCH%"=="" (
    echo [!] Chua nhap branch!
    popd
    pause
    exit /b 1
)

:: Save to config
if not exist "config" mkdir config
echo %BRANCH%> config\current_branch.txt

echo.
echo [*] Da luu branch: %BRANCH%
echo [*] Dang cap nhat...
echo.

:: Run update
call UPDATE.bat

popd
