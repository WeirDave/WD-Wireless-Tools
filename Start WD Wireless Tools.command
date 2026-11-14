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

# One function, called last, with `exit` after it: bash reads a script by byte
# offset, and an update replaces this file while the old window is still
# waiting on python. Everything it needs is read before the server starts.
run_server() {
    local port="${PORT:-8675}" pid
    # Only the port this run will use, and only a process running server.py.
    # SIGTERM first: SIGKILL gave a stale instance no chance to close cleanly.
    for pid in $(lsof -ti tcp:"$port" -sTCP:LISTEN 2>/dev/null); do
        if ps -p "$pid" -o command= 2>/dev/null | grep -q "server.py"; then
            kill "$pid" 2>/dev/null
            sleep 1
            kill -0 "$pid" 2>/dev/null && kill -9 "$pid" 2>/dev/null
        fi
    done

    python3 server.py

    echo
    echo "WD Wireless Tools has closed."
}

run_server
exit $?
