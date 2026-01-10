@echo off
:: Add IPv6 Address to Windows Interface
:: RUN AS ADMINISTRATOR!

echo ============================================
echo IPv6 Setup Script
echo ============================================
echo.

:: Check admin
net session >nul 2>&1
if %errorLevel% neq 0 (
    echo [ERROR] Please run as Administrator!
    echo Right-click this file and select "Run as administrator"
    pause
    exit /b 1
)

:: Add first IPv6 from the list
echo Adding IPv6 address to Ethernet...
netsh interface ipv6 add address "Ethernet" 2001:ee0:b004:1f00::2

echo.
echo Verifying...
netsh interface ipv6 show addresses "Ethernet" | findstr "2001:"

echo.
echo Testing connectivity...
ping -n 1 2001:4860:4860::8888

echo.
echo ============================================
echo Done! If ping shows "Reply from", IPv6 works!
echo ============================================
pause
