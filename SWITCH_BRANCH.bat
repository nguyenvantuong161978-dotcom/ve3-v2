@echo off
:: VE3 Tool - Switch to new branch (run once)
:: Chay file nay MOT LAN de chuyen sang phien ban moi

cd /d "%~dp0"

echo ========================================
echo   SWITCH TO NEW BRANCH
echo ========================================
echo.

:: Doc branch tu config file
set BRANCH=main
if exist "config\current_branch.txt" (
    set /p BRANCH=<config\current_branch.txt
)
echo [*] Target branch: %BRANCH%
echo.

:: Check git
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Git not found!
    echo Please install git or download ZIP manually:
    echo https://github.com/criggerbrannon-hash/ve3-tool/archive/refs/heads/%BRANCH%.zip
    goto :end
)

echo [*] Fetching new branch...
git fetch origin %BRANCH%

echo [*] Switching to new branch...
git checkout %BRANCH%
git reset --hard origin/%BRANCH%

echo.
echo ========================================
echo   DONE! Now run RUN.bat as usual
echo ========================================
echo.

:end
pause
