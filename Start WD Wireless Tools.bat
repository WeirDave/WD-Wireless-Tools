@echo off
title WD Wireless Tools
cd /d "%~dp0"

if exist "%~dp0.git" (
    where git >nul 2>&1 && (
        echo Checking for updates...
        git pull
        echo.
    )
)

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
