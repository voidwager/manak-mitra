@echo off
REM ===========================================================================
REM  Manak Mitra - one-time setup
REM
REM  Installs everything a fresh machine needs:
REM    1. Python virtualenv + backend packages   (backend/requirements.txt)
REM    2. Frontend packages                       (frontend/package.json)
REM    3. .env from the template
REM    4. Database tables + synthetic demo data
REM
REM  Safe to re-run - it skips what is already done.
REM  After this, use start.bat to run the workbench.
REM ===========================================================================

setlocal
cd /d "%~dp0"
set "ROOT=%CD%"
set "PYTHON=%ROOT%\backend\.venv\Scripts\python.exe"

echo.
echo  Manak Mitra - setup
echo  =========================
echo.

REM --- prerequisites ---------------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo  [X] Python is not on PATH.
    echo      Install Python 3.10 or newer from https://python.org
    echo      and tick "Add python.exe to PATH" during setup.
    echo.
    pause
    exit /b 1
)

where npm >nul 2>&1
if errorlevel 1 (
    echo  [X] Node.js / npm is not on PATH.
    echo      Install Node 20 or newer from https://nodejs.org
    echo.
    pause
    exit /b 1
)

for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo  Found %%v
for /f "tokens=*" %%v in ('node --version 2^>^&1') do echo  Found Node %%v
echo.

REM --- 1. backend virtualenv -------------------------------------------------
REM A virtualenv hard-codes the absolute path of the Python that created it,
REM so one copied from another machine looks present but cannot run. Checking
REM that the file exists is not enough - actually execute it.
set "VENV_OK=0"
if exist "%PYTHON%" (
    "%PYTHON%" -c "import sys" >nul 2>&1
    if not errorlevel 1 set "VENV_OK=1"
)

if "%VENV_OK%"=="1" (
    echo  [1/4] Virtualenv is healthy - skipping creation.
) else (
    if exist "%ROOT%\backend\.venv" (
        echo  [1/4] Virtualenv is broken ^(copied from another PC^) - rebuilding...
        rmdir /s /q "%ROOT%\backend\.venv"
    ) else (
        echo  [1/4] Creating virtualenv...
    )
    python -m venv "%ROOT%\backend\.venv"
    if errorlevel 1 (
        echo  [X] Failed to create the virtualenv.
        pause
        exit /b 1
    )
)

echo        Installing backend packages...
"%PYTHON%" -m pip install --upgrade pip --quiet
"%PYTHON%" -m pip install -r "%ROOT%\backend\requirements.txt" --quiet
if errorlevel 1 (
    echo  [X] Backend install failed. Scroll up for the error.
    pause
    exit /b 1
)
echo        Backend packages installed.
echo.

REM --- 2. frontend packages --------------------------------------------------
echo  [2/4] Installing frontend packages ^(this takes a minute^)...
pushd "%ROOT%\frontend"
call npm install --silent
if errorlevel 1 (
    echo  [X] npm install failed. Scroll up for the error.
    popd
    pause
    exit /b 1
)
popd
echo        Frontend packages installed.
echo.

REM --- 3. environment file ---------------------------------------------------
if exist "%ROOT%\.env" (
    echo  [3/4] .env already exists - leaving it alone.
) else (
    echo  [3/4] Creating .env from the template...
    copy /y "%ROOT%\.env.example" "%ROOT%\.env" >nul
    echo        Created .env
)
echo.

REM --- 4. database -----------------------------------------------------------
echo  [4/4] Creating tables and loading demo data...
"%PYTHON%" "%ROOT%\scripts\seed_db.py"
if errorlevel 1 (
    echo  [X] Database setup failed. Scroll up for the error.
    pause
    exit /b 1
)
echo.

REM --- done ------------------------------------------------------------------
echo  ==========================================================
echo   Setup complete.
echo.
echo   Before chatting, open .env and set:
echo       MODEL_PROVIDER=groq
echo       GROQ_API_KEY=...        ^(from console.groq.com^)
echo       MODEL_NAME=...          ^(run start.bat, then open
echo                                http://localhost:8000/api/models^)
echo.
echo   Then run:  start.bat
echo  ==========================================================
echo.
pause
exit /b 0
