@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if errorlevel 1 (
    echo Python was not found. Install Python and run: python -m pip install -r requirements.txt
    pause
    exit /b 1
)
start "" pythonw "%~dp0main.py"
