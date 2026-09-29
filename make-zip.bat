@echo off
REM ===========================================================================
REM  Manak Mitra - build a shareable zip
REM
REM  Creates manak-mitra.zip next to this folder, excluding everything that
REM  is machine-specific or regenerated:
REM
REM    backend\.venv          hard-codes this PC's Python path - breaks elsewhere
REM    frontend\node_modules  large, can hold platform-specific binaries
REM    .env                   your API key - the recipient uses their own
REM    data\*.db              your conversations
REM    frontend\dist          build output
REM
REM  The recipient unzips anywhere and runs install.bat
REM ===========================================================================

setlocal
cd /d "%~dp0"
set "ROOT=%CD%"
set "OUT=%ROOT%\..\manak-mitra.zip"
set "STAGE=%TEMP%\manak-zip-stage"

echo.
echo  Building a shareable zip...
echo.

if exist "%STAGE%" rmdir /s /q "%STAGE%"
mkdir "%STAGE%"

echo   Copying project files...
robocopy "%ROOT%" "%STAGE%" /E /NFL /NDL /NJH /NJS /NP ^
    /XD ".venv" "node_modules" "dist" "__pycache__" ".pytest_cache" ".git" ^
    /XF ".env" "*.db" "*.sqlite" "*.sqlite3" "*.log" >nul

REM robocopy uses exit codes 0-7 for success.
if errorlevel 8 (
    echo  [X] Copy failed.
    pause
    exit /b 1
)

if exist "%OUT%" del /q "%OUT%"

echo   Compressing...
powershell -NoProfile -Command "Compress-Archive -Path '%STAGE%\*' -DestinationPath '%OUT%' -Force"
if errorlevel 1 (
    echo  [X] Compression failed.
    rmdir /s /q "%STAGE%"
    pause
    exit /b 1
)

rmdir /s /q "%STAGE%"

echo.
echo  ==========================================================
echo   Created:  %OUT%
echo.
echo   Tell whoever receives it:
echo     1. Unzip anywhere ^(spaces in the path are fine^)
echo     2. Double-click install.bat
echo     3. Put their own GROQ_API_KEY in .env
echo     4. Double-click start.bat
echo.
echo   They need Python 3.10+ and Node 20+ on PATH.
echo  ==========================================================
echo.
pause
exit /b 0
