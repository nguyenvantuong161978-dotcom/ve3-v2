@echo off
chcp 65001 >nul
pushd "%~dp0"

echo ========================================
echo   VE3 Tool - CAP NHAT
echo ========================================
echo.

:: Show current branch
set BRANCH=main
if exist "config\current_branch.txt" (
    set /p BRANCH=<config\current_branch.txt
)
echo [*] Branch: %BRANCH%
echo.

:: Run update
python UPDATE.py
set RESULT=%errorlevel%

echo.
echo ========================================
if %RESULT% equ 0 (
    echo   [OK] CAP NHAT THANH CONG!
    echo   Branch: %BRANCH%
) else (
    echo   [!] CAP NHAT THAT BAI
    echo   Dang dung ban local
)
echo ========================================
echo.

popd
echo Nhan phim bat ky de dong...
pause >nul
