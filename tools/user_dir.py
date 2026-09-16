"""Where the suite keeps the things a person configures.

One place, and an override, because the lack of one has now cost real data
twice in a night. Automated UI checks drive the real pages against a real
server, every page writes its preferences as you use it, and with the path
hard-coded in eight modules there was nowhere else for those writes to go: a
sweep that clicked every option on every report wrote them all into his live
`settings.json`, and a debounce meant the last few landed as intermediate
values. Eight of his saved defaults were wrong afterwards, including one that
hides every omni AP from two reports.

So: set `WD_USER_DIR` to a scratch directory before starting a server you are
going to drive automatically, and his real configuration cannot be reached.

    WD_USER_DIR=/tmp/wd-test python server.py

**Read once, at import.** These are module-level constants all over the suite
and making them dynamic would mean auditing every read; setting the variable
before the process starts is the supported way and the only one tested.
"""
from __future__ import annotations

import os
from pathlib import Path

ENV_VAR = "WD_USER_DIR"
DEFAULT = Path.home() / ".wd_wireless_tools"


def user_dir() -> Path:
    """The user-data directory, honouring `WD_USER_DIR` when it is set."""
    override = os.environ.get(ENV_VAR)
    if override:
        return Path(override).expanduser()
    return DEFAULT
