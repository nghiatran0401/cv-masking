@echo off
setlocal
title Install CV Masking
set "SRC=%~dp0"
set "DEST=%LOCALAPPDATA%\Programs\CVMasking"

if not exist "%SRC%python\python.exe" (
    echo Unzip the whole package first, then run "Install CV Masking.bat" from the unzipped folder.
    pause
    exit /b 1
)
if /i "%SRC%"=="%DEST%\" goto shortcut

echo Installing CV Masking for this Windows user into:
echo   %DEST%
echo If CV Masking is open, close its window first.
echo.

rem /MIR replaces the program folders only. The data folder with your work is left alone.
robocopy "%SRC%python" "%DEST%\python" /MIR /R:2 /W:2 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto failed
robocopy "%SRC%backend" "%DEST%\backend" /MIR /R:2 /W:2 /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 goto failed
copy /y "%SRC%Start CV Masking.bat" "%DEST%\" >nul || goto failed
copy /y "%SRC%HUONG-DAN.txt" "%DEST%\" >nul || goto failed

:shortcut
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$d = $env:DEST; $s = (New-Object -ComObject WScript.Shell).CreateShortcut([IO.Path]::Combine([Environment]::GetFolderPath('Desktop'), 'CV Masking.lnk')); $s.TargetPath = [IO.Path]::Combine($d, 'Start CV Masking.bat'); $s.WorkingDirectory = $d; $s.IconLocation = [IO.Path]::Combine($d, 'python\python.exe') + ',0'; $s.Save()"
if errorlevel 1 (
    echo The desktop shortcut could not be created. Open this folder and double-click "Start CV Masking.bat":
    echo   %DEST%
) else (
    echo A "CV Masking" shortcut is on your desktop.
)

echo.
echo CV Masking is installed and will start now.
start "" "%DEST%\Start CV Masking.bat"
exit /b 0

:failed
echo.
echo Install failed. Close the CV Masking window if it is open, then run this file again.
echo If it still fails, send IT a photo of this window.
pause
exit /b 1
