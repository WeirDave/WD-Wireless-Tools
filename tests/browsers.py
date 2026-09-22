"""Where the browsers are, asked once instead of fourteen times.

**Fourteen test files each carried the same three hardcoded Windows paths**,
and a path is a machine's answer rather than a fact. On his machine they are
right. On a GitHub runner, on a Mac, or on a Windows box where Firefox was
installed per-user, they are not - and the tests that drive real controls,
which this repository treats as its standard of proof, skip silently and the
suite reports green.

That is not hypothetical. Those files were skipping in CI for a different
reason - `selenium` was never installed there - and it hid a test that had
been red since v2.163.0 through four releases. The paths would have been the
next thing to hide them.

So: ask the machine. A known install location if it is there, then `PATH`,
then the standard application directory for the platform. Every answer is a
path that exists, or a sentinel that cannot.

**The sentinel is deliberately not the empty string.** `Path("").exists()`
is `Path(".")`, which is true - so an empty answer would turn "no browser
here" into "the current directory is Firefox", and every skip guard in the
suite reads `Path(BINARY).exists()`. It is a path that cannot be created
instead, so those guards keep working untouched.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

#: Returned when a browser is not on this machine. Not "" - see the module
#: docstring; an empty path is the current directory and exists.
NOT_INSTALLED = os.path.join(os.sep, "(no such browser on this machine)")

#: Known install locations, in the order they are worth trying, plus the
#: names to look for on `PATH`. Windows first because that is what he runs
#: and what the release is built for.
_WHERE = {
    "firefox": {
        "paths": [
            r"C:\Program Files\Mozilla Firefox\firefox.exe",
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Mozilla Firefox\firefox.exe"),
            "/Applications/Firefox.app/Contents/MacOS/firefox",
            "/usr/bin/firefox",
            "/snap/bin/firefox",
        ],
        "which": ["firefox"],
    },
    "chrome": {
        "paths": [
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(
                r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/usr/bin/google-chrome",
            "/usr/bin/chromium-browser",
        ],
        "which": ["chrome", "google-chrome", "chromium", "chromium-browser"],
    },
    "edge": {
        "paths": [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
            "/usr/bin/microsoft-edge",
        ],
        "which": ["msedge", "microsoft-edge", "microsoft-edge-stable"],
    },
}


def find(kind: str) -> str:
    """The binary for `kind`, or `NOT_INSTALLED`.

    `kind` is "firefox", "chrome" or "edge". An unknown name is a
    programming error rather than a missing browser, so it raises.
    """
    where = _WHERE[kind]
    for candidate in where["paths"]:
        if candidate and Path(candidate).is_file():
            return candidate
    for name in where["which"]:
        found = shutil.which(name)
        if found:
            return found
    return NOT_INSTALLED


def installed(kind: str) -> bool:
    return find(kind) != NOT_INSTALLED


def available() -> list:
    """Which of the three this machine can actually drive."""
    return [k for k in ("firefox", "chrome", "edge") if installed(k)]


def triple() -> list:
    """`[(kind, binary), ...]` in the order the suite has always used.

    Every browser is listed whether or not it is present - the tests skip on
    a binary that does not exist, and returning only what is installed would
    silently shrink the matrix instead of reporting a gap.
    """
    return [(k, find(k)) for k in ("firefox", "chrome", "edge")]


def on_ci() -> bool:
    """GitHub sets `CI=true`; so does most of the rest of the world."""
    return os.environ.get("CI", "").lower() in ("1", "true", "yes")


def why_missing() -> str:
    """A sentence for a skip message, naming what was looked for."""
    return ("no browser found - looked for %s on PATH and in the usual "
            "install locations for %s"
            % (", ".join(sorted(
                n for w in _WHERE.values() for n in w["which"])),
               sys.platform))
