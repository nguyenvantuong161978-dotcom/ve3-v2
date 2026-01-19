@echo off
echo ============================================
echo  CLEANUP AND FIX - Encoding Issues
echo ============================================
echo.

echo [1/4] Killing all Python processes...
taskkill /F /IM python.exe 2>nul
taskkill /F /IM pythonw.exe 2>nul
timeout /t 2 /nobreak >nul

echo [2/4] Killing all Chrome processes...
taskkill /F /IM chrome.exe 2>nul
taskkill /F /IM GoogleChromePortable.exe 2>nul
timeout /t 2 /nobreak >nul

echo [3/4] Deleting ALL Python cache files...
for /d /r . %%d in (__pycache__) do @if exist "%%d" rd /s /q "%%d" 2>nul
del /s /q *.pyc 2>nul
echo     Done!

echo [4/4] Running UPDATE.py...
python UPDATE.py

echo.
echo ============================================
echo  CLEANUP COMPLETE!
echo ============================================
echo.
echo Now run: python vm_manager_gui.py
echo.
pause
