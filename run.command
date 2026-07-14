#!/bin/bash
# WD Wireless Tools launcher (macOS) — starts the local server and opens your browser.
# Double-click this file, or run from Terminal: bash run.command

cd "$(dirname "$0")"

# First run: install dependencies if Flask isn't present yet.
python3 -c "import flask" 2>/dev/null || python3 -m pip install -r requirements.txt

python3 server.py
