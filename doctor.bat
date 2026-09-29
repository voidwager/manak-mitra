@echo off
REM ===========================================================================
REM  Manak Mitra - diagnose a machine where the app looks wrong
REM
REM  Double-click this file. It reports which of the four things that differ
REM  between machines is at fault - the checkout, .env, the database, or the
REM  installed packages - and prints the exact command that fixes it.
REM
REM  Prints no API keys, so the output is safe to share when asking for help.
REM ===========================================================================

setlocal
cd /d "%~dp0"
set "PYTHON=%CD%\backend\.venv\Scripts\python.exe"

if not exist "%PYTHON%" (
    echo.
    echo  [X] The backend virtualenv does not exist yet.
    echo      Run install.bat first - that creates it.
    echo.
    pause
    exit /b 1
)

"%PYTHON%" "%CD%\scripts\doctor.py"

echo.
pause
exit /b 0
