@echo off
:: VE3 Tool - Switch to new branch
:: Chay file nay de chuyen sang branch moi

:: Use pushd for UNC path support (VMware, RDP shared folders)
pushd "%~dp0"

echo ========================================
echo   SWITCH TO NEW BRANCH
echo ========================================
echo.

:: Doc branch hien tai tu config file
set CURRENT_BRANCH=
if exist "config\current_branch.txt" (
    set /p CURRENT_BRANCH=<config\current_branch.txt
)

echo [*] Current branch: %CURRENT_BRANCH%
echo.

:: Hoi nguoi dung nhap branch moi
echo Nhap branch moi (hoac Enter de giu nguyen):
set /p NEW_BRANCH="> "

:: Neu nguoi dung khong nhap gi, giu nguyen branch cu
if "%NEW_BRANCH%"=="" (
    if "%CURRENT_BRANCH%"=="" (
        echo [ERROR] Khong co branch nao duoc chi dinh!
        goto :end
    )
    set NEW_BRANCH=%CURRENT_BRANCH%
    echo [*] Giu nguyen branch: %NEW_BRANCH%
) else (
    echo [*] Branch moi: %NEW_BRANCH%
    :: Luu branch moi vao file
    echo %NEW_BRANCH%> config\current_branch.txt
    echo [*] Da luu vao config\current_branch.txt
)

echo.

:: Check git
where git >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Git not found!
    echo Please install git or download ZIP manually
    goto :end
)

echo [*] Fetching branch: %NEW_BRANCH%...
git fetch origin %NEW_BRANCH%

if %errorlevel% neq 0 (
    echo [ERROR] Khong tim thay branch: %NEW_BRANCH%
    echo Kiem tra lai ten branch!
    goto :end
)

echo [*] Switching to branch: %NEW_BRANCH%...
git checkout %NEW_BRANCH% 2>nul || git checkout -b %NEW_BRANCH% origin/%NEW_BRANCH%
git reset --hard origin/%NEW_BRANCH%

echo.
echo ========================================
echo   DONE! Da chuyen sang: %NEW_BRANCH%
echo   Bay gio chi can chay RUN.bat
echo ========================================
echo.

:end
popd
pause
