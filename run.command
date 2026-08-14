#!/bin/bash

cd "$(dirname "$0")"

if [ -d "$(dirname "$0")/.git" ] && command -v git >/dev/null 2>&1; then
    echo "Checking for updates..."
    git pull
    echo
fi

python3 -c "import flask, waitress, requests, browser_cookie3, cryptography, keyring" 2>/dev/null || python3 -m pip install -r requirements.txt

lsof -ti tcp:8675 -sTCP:LISTEN 2>/dev/null | xargs -r kill -9 2>/dev/null

while true; do
    rm -f "$(dirname "$0")/.restart_requested"
    python3 server.py
    if [ -f "$(dirname "$0")/.restart_requested" ]; then
        rm -f "$(dirname "$0")/.restart_requested"
        continue
    fi
    break
done
