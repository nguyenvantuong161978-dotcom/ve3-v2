@echo off
:: ============================================
:: VE3 Tool - Cai dat may moi (KHONG CAN GIT)
:: ============================================
:: Chi can copy file nay vao may moi va chay!
:: Se tu dong tai tool va cai dat dependencies.
:: ============================================

setlocal enabledelayedexpansion

echo ========================================
echo   VE3 TOOL - CAI DAT MAY MOI
echo   (Khong can Git - Khong can dang nhap)
echo ========================================
echo.

:: Config
set REPO=criggerbrannon-hash/ve3-tool-simple
set BRANCH=claude/tool-development-cleanup-HwBB2
set ZIP_URL=https://github.com/%REPO%/archive/refs/heads/%BRANCH%.zip
set FOLDER_NAME=ve3-tool-simple-%BRANCH:-=-%

:: Kiem tra Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo [ERROR] Chua cai Python!
    echo         Tai tai: https://www.python.org/downloads/
    echo         Nho tick "Add Python to PATH" khi cai!
    pause
    exit /b 1
)
echo [OK] Python da cai

:: Tao thu muc
set INSTALL_DIR=%USERPROFILE%\ve3-tool
echo.
echo [*] Se cai vao: %INSTALL_DIR%
echo.

if exist "%INSTALL_DIR%" (
    echo [!] Thu muc da ton tai!
    echo     1. Ghi de ^(xoa cu, tai moi^)
    echo     2. Chi update ^(giu du lieu^)
    echo     3. Huy
    choice /c 123 /n /m "Chon [1/2/3]: "
    if errorlevel 3 exit /b 0
    if errorlevel 2 goto :update_only
    if errorlevel 1 (
        echo [*] Xoa thu muc cu...
        rmdir /s /q "%INSTALL_DIR%" 2>nul
    )
)

:install_fresh
mkdir "%INSTALL_DIR%" 2>nul
pushd "%INSTALL_DIR%"

:: Tai ZIP
echo.
echo [*] Dang tai tu GitHub...
echo     URL: %ZIP_URL%

curl -L -o ve3-tool.zip "%ZIP_URL%"
if %errorlevel% neq 0 (
    echo [ERROR] Khong tai duoc! Kiem tra ket noi mang.
    pause
    exit /b 1
)
echo [OK] Da tai xong!

:: Giai nen
echo.
echo [*] Dang giai nen...
tar -xf ve3-tool.zip
if %errorlevel% neq 0 (
    powershell -command "Expand-Archive -Path 've3-tool.zip' -DestinationPath '.' -Force"
)

:: Di chuyen files ra ngoai
for /d %%i in (ve3-tool-simple-*) do (
    xcopy /e /y "%%i\*" "." >nul
    rmdir /s /q "%%i"
)
del ve3-tool.zip

goto :install_deps

:update_only
pushd "%INSTALL_DIR%"
echo.
echo [*] Dang update...
python UPDATE.py
goto :done

:install_deps
:: Cai dependencies
echo.
echo [*] Cai dat dependencies...
pip install -r requirements.txt

:: Tao shortcut tren Desktop
echo.
echo [*] Tao shortcut tren Desktop...
set DESKTOP=%USERPROFILE%\Desktop
echo @echo off > "%DESKTOP%\VE3 Tool.bat"
echo pushd "%INSTALL_DIR%" >> "%DESKTOP%\VE3 Tool.bat"
echo call RUN.bat >> "%DESKTOP%\VE3 Tool.bat"
echo popd >> "%DESKTOP%\VE3 Tool.bat"

:done
popd
echo.
echo ========================================
echo   CAI DAT THANH CONG!
echo ========================================
echo.
echo   Thu muc: %INSTALL_DIR%
echo   Shortcut: Desktop\VE3 Tool.bat
echo.
echo   Cach chay:
echo   - Double-click "VE3 Tool.bat" tren Desktop
echo   - Hoac vao %INSTALL_DIR% va chay RUN.bat
echo.
echo ========================================
pause
