#!/bin/bash

cd "$(dirname "$0")"

# Present is not current: the check reads the version floors in
# requirements.txt, so an old package that still imports is upgraded too.
# Exit 2 is "installed, but older than a floor" - the app still runs, so a
# failed upgrade (offline, say) warns and carries on rather than refusing.
python3 -m tools.deps >/dev/null 2>&1
deps_status=$?
if [ "$deps_status" -ne 0 ]; then
    echo
    echo "Installing or updating required Python packages..."
    if ! python3 -m pip install --disable-pip-version-check -q --upgrade -r requirements.txt; then
        if [ "$deps_status" -eq 2 ]; then
            echo "Could not update some packages. Starting with the versions installed."
        else
            echo "Some packages failed to install. Try: python3 -m pip install -r requirements.txt"
            exit 1
        fi
    fi
fi

lsof -ti tcp:8675 -sTCP:LISTEN 2>/dev/null | xargs -r kill -9 2>/dev/null

python3 server.py

echo
echo "WD Wireless Tools has closed."
