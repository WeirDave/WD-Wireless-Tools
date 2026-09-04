@echo off
title WD Wireless Tools
cd /d "%~dp0"

REM No update here on purpose. Installs sit on a release tag with HEAD
REM detached, which is the intended state - so a bare "git pull" has no branch
REM to merge and printed a raw git error on every launch. Updating is the app's
REM job: it checks on start and offers the update in About, on the release
REM channel the user chose.

REM ---- Check for Python -------------------------------------------------------
where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo  Python is not installed, and WD Wireless Tools needs it to run.
    echo.
    echo  How to install Python:
    echo.
    echo    Option 1 - Download from python.org:
    echo      1. Go to https://www.python.org/downloads/
    echo      2. Click the big yellow "Download Python" button
    echo      3. Run the installer
    echo      4. IMPORTANT: On the first screen, tick "Add python.exe to PATH"
    echo      5. Click "Install Now"
    echo.
    echo    Option 2 - Install from a terminal (PowerShell or Command Prompt):
    echo      winget install --id Python.Python.3.12 -e
    echo.
    echo  After installing Python, close this window and double-click
    echo  "Start WD Wireless Tools.bat" again.
    echo.
    pause
    exit /b 1
)

REM ---- Check for dependencies -------------------------------------------------
python -c "import flask, waitress, requests, browser_cookie3, cryptography, keyring, PIL" 2>nul
if errorlevel 1 (
    echo.
    echo  First-time setup: installing required Python packages...
    echo  This only needs to happen once and takes about a minute.
    echo.
    python -m pip install --disable-pip-version-check -q -r requirements.txt
    if errorlevel 1 (
        echo.
        echo  Some packages failed to install.
        echo.
        echo  Try running this command yourself in PowerShell or Command Prompt:
        echo    python -m pip install -r "%~dp0requirements.txt"
        echo.
        echo  If pip itself is missing, run:
        echo    python -m ensurepip --upgrade
        echo  then try the pip install command above again.
        echo.
        pause
        exit /b 1
    )
    echo.
    echo  Done. Starting WD Wireless Tools...
    echo.
)

REM ---- Kill any stale instance on port 8675 -----------------------------------
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8675 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1

REM ---- Launch -----------------------------------------------------------------
python server.py

if errorlevel 1 (
    echo.
    echo WD Wireless Tools could not start. Review the error above.
) else (
    echo.
    echo WD Wireless Tools has closed normally.
)

pause
