@echo off
setlocal
title CV Masking - keep this window open while you work
cd /d "%~dp0"

if not exist "python\python.exe" (
    echo CV Masking is incomplete. Unzip the whole package again, then run "Install CV Masking.bat".
    pause
    exit /b 1
)

echo CV Masking is starting. Your browser will open http://127.0.0.1:8765
echo Close this window to quit CV Masking.
"python\python.exe" -I -m cv_masking --desktop
if errorlevel 1 (
    echo.
    echo CV Masking stopped with an error. Send IT a photo of this window.
    pause
)
