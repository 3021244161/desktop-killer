@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Create-Desktop-Shortcut.ps1"
if errorlevel 1 (
    echo.
    echo Could not create the desktop shortcut. Keep the complete game folder and try again.
    pause
    exit /b 1
)
echo.
echo Desktop shortcut is ready.
pause
endlocal
