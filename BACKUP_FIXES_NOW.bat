@echo off
echo ========================================
echo BACKUP FIXES TO GITHUB - SAFE METHOD
echo ========================================
echo.

cd /d "%~dp0"

echo Creating backup branch...
git checkout -b excel-fixes-2026-01-23-BACKUP
if errorlevel 1 (
    echo ERROR: Could not create branch!
    pause
    exit /b 1
)

echo.
echo Pushing to GitHub...
git push origin excel-fixes-2026-01-23-BACKUP
if errorlevel 1 (
    echo ERROR: Could not push to GitHub!
    echo Check your internet connection and git credentials.
    pause
    exit /b 1
)

echo.
echo ========================================
echo SUCCESS! Fixes backed up to GitHub!
echo ========================================
echo.
echo Branch: excel-fixes-2026-01-23-BACKUP
echo URL: https://github.com/nguyenvantuong161978-dotcom/ve3-tool-simple/tree/excel-fixes-2026-01-23-BACKUP
echo.

echo Switching back to main...
git checkout main

echo.
echo Done! Your fixes are safe on GitHub.
echo.
pause
