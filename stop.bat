@echo off
REM ===========================================================================
REM  Manak Mitra - stop backend + frontend
REM
REM  Kills whatever is listening on 8000 (API) and 5173 (frontend).
REM  Safe to run when nothing is up.
REM ===========================================================================

setlocal
echo.
echo  Stopping the workbench...
echo.

call :killport 8000 backend
call :killport 5173 frontend

echo.
ping -n 3 127.0.0.1 >nul
exit /b 0

REM ===========================================================================
:killport
set "FOUND="
for /f "tokens=5" %%p in ('netstat -ano -p TCP ^| findstr /r /c:":%~1 .*LISTENING"') do (
    taskkill /f /pid %%p >nul 2>&1
    if not errorlevel 1 (
        echo   stopped %~2 ^(pid %%p^)
        set "FOUND=1"
    )
)
if not defined FOUND echo   %~2 was not running
exit /b 0
