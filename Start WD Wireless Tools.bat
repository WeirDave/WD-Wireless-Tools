@echo off
title WD Wireless Tools
cd /d "%~dp0"

REM No update here on purpose. Installs sit on a release tag with HEAD
REM detached, which is the intended state - so a bare "git pull" has no branch
REM to merge and printed a raw git error on every launch. Updating is the app's
REM job: it checks on start and offers the update in About, on the release
REM channel the user chose.

python -c "import flask, waitress, requests, browser_cookie3, cryptography, keyring" 2>nul || python -m pip install -r requirements.txt

powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8675 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1

python server.py

if errorlevel 1 (
    echo.
    echo WD Wireless Tools could not start. Review the error above.
) else (
    echo.
    echo WD Wireless Tools has closed normally.
)

pause
