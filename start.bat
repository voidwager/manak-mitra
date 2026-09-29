@echo off
REM ===========================================================================
REM  SYNQ Workbench - start backend + frontend
REM
REM  Double-click this file, or run it from a terminal:
REM      start.bat
REM
REM  Batch is used instead of PowerShell because .ps1 files are blocked by
REM  Windows execution policy by default. .bat has no such restriction.
REM
REM  Each server opens in its own window so their logs stay readable and you
REM  can Ctrl+C one without killing the other. Close both with stop.bat
REM ===========================================================================

setlocal enabledelayedexpansion
cd /d "%~dp0"

set "ROOT=%CD%"
set "PYTHON=%ROOT%\backend\.venv\Scripts\python.exe"

echo.
echo  SYNQ Workbench
echo  =================
echo.

REM --- checks ---------------------------------------------------------------
if not exist "%PYTHON%" (
    echo  [X] Backend virtualenv missing.
    echo.
    echo      Create it with:
    echo        cd backend
    echo        python -m venv .venv
    echo        .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist "%ROOT%\frontend\node_modules" (
    echo  [X] Frontend dependencies missing.
    echo.
    echo      Install them with:
    echo        cd frontend
    echo        npm install
    echo.
    pause
    exit /b 1
)

if not exist "%ROOT%\.env" (
    echo  [!] No .env found - copying the template.
    copy /y "%ROOT%\.env.example" "%ROOT%\.env" >nul
    echo      Created .env. Set MODEL_PROVIDER, MODEL_NAME and GROQ_API_KEY in it,
    echo      then restart this script.
    echo.
)

REM --- free the ports so a stale process does not silently win ---------------
echo  Clearing ports 8000 and 5173...
call :killport 8000
call :killport 5173

REM --- launch ---------------------------------------------------------------
echo  Starting backend...
start "SYNQ Backend" cmd /k "cd /d "%ROOT%\backend" && echo BACKEND  http://localhost:8000 && .venv\Scripts\python.exe -m uvicorn app.main:app --reload --port 8000"

echo  Starting frontend...
start "SYNQ Frontend" cmd /k "cd /d "%ROOT%\frontend" && echo FRONTEND  http://localhost:5173 && npm run dev"

REM --- wait for both to answer ----------------------------------------------
echo.
echo  Waiting for servers...

set BACKEND_UP=0
set FRONTEND_UP=0

for /l %%i in (1,1,30) do (
    if !BACKEND_UP!==0 (
        curl -s -o nul --max-time 2 http://127.0.0.1:8000/api/health && set BACKEND_UP=1
    )
    if !FRONTEND_UP!==0 (
        curl -s -o nul --max-time 2 http://127.0.0.1:5173/ && set FRONTEND_UP=1
    )
    if !BACKEND_UP!==1 if !FRONTEND_UP!==1 goto :ready
    ping -n 2 127.0.0.1 >nul
)

:ready
echo.
if "%BACKEND_UP%"=="1" (
    echo  [OK] backend    http://localhost:8000/docs
) else (
    echo  [X]  backend did not start - check the "SYNQ Backend" window
)
if "%FRONTEND_UP%"=="1" (
    echo  [OK] frontend   http://localhost:5173
) else (
    echo  [X]  frontend did not start - check the "SYNQ Frontend" window
)

echo.
if "%BACKEND_UP%"=="1" if "%FRONTEND_UP%"=="1" (
    echo  Opening the app...
    start "" http://localhost:5173
)

echo.
echo  Stop both with:  stop.bat
echo.
ping -n 5 127.0.0.1 >nul
exit /b 0

REM ===========================================================================
:killport
REM Kill whatever is LISTENING on the given port.
for /f "tokens=5" %%p in ('netstat -ano -p TCP ^| findstr /r /c:":%~1 .*LISTENING"') do (
    taskkill /f /pid %%p >nul 2>&1
)
exit /b 0
