@echo off
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

:start
del "%~dp0.restart_requested" >nul 2>&1
python server.py
IF EXIST "%~dp0.restart_requested" (
    del "%~dp0.restart_requested" >nul 2>&1
    GOTO start
)
pause
