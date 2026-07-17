@echo off
cd /d "%~dp0"
where pythonw >nul 2>nul
if errorlevel 1 (
    echo Python with Tkinter is required to run Side Translate.
    pause
    exit /b 1
)
start "SideTranslate" /b pythonw main.py
