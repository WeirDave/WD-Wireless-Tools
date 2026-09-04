#!/bin/bash

cd "$(dirname "$0")"

# No update here on purpose. Installs sit on a release tag with HEAD detached,
# which is the intended state - so a bare "git pull" has no branch to merge and
# printed a raw git error on every launch. Updating is the app's job: it checks
# on start and offers the update in About, on the release channel the user chose.

python3 -c "import flask, waitress, requests, browser_cookie3, cryptography, keyring" 2>/dev/null || python3 -m pip install -r requirements.txt

lsof -ti tcp:8675 -sTCP:LISTEN 2>/dev/null | xargs -r kill -9 2>/dev/null

python3 server.py

echo
echo "WD Wireless Tools has closed."
