@echo off
REM WD Wireless Tools launcher — starts the local server and opens your browser.
cd /d "%~dp0"

REM First run: install dependencies if Flask isn't present yet.
python -c "import flask" 2>nul || python -m pip install -r requirements.txt

python server.py
pause
