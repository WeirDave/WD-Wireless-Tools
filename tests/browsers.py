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

import contextlib
import os
import signal
import subprocess
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


# ── stopping one, and meaning it ───────────────────────────────────────────

def _pid_alive(pid: int) -> bool:
    if not pid:
        return False
    if os.name == "nt":
        out = subprocess.run(
            ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
            capture_output=True, text=True, errors="replace").stdout
        return str(pid) in out
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _kill(pid: int) -> None:
    if not pid:
        return
    if os.name == "nt":
        # /T so the browser's own content processes go with it - Firefox keeps
        # about ten per window, which is what turns a leak into gigabytes.
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                       capture_output=True, text=True, errors="replace")
        return
    with contextlib.suppress(OSError):
        os.kill(pid, signal.SIGKILL)


def shut_down(driver) -> list:
    """`driver.quit()`, and then make sure the browser is actually gone.

    **`quit()` inside a suppress-everything block looks unconditional and is
    not.** When the driver has stopped answering - which is what happens under
    memory pressure, precisely when a leak costs the most - `quit()` raises,
    the exception is swallowed by the `contextlib.suppress(Exception)` that
    was put there to make teardown unconditional, and the browser it started
    outlives the run.

    Measured on 2026-09-21: three headless Firefox processes left behind by a
    suite whose teardown looks correct, with 2 GB of 32 GB free, and the next
    browser run died with `ConnectionResetError` before its first assertion.
    That is the same shape as the 307 processes and 22.5 GB recorded in
    CLAUDE.md, arriving through a door that had already been closed once.

    So the browser's own pid is read *before* quitting and killed afterwards
    if it is still there. Firefox reports it as `moz:processID`; Chromium does
    not report one, and there the driver process is the parent that takes the
    browser with it, so the driver's pid is the one to check.

    Returns the pids it had to kill, so a caller can say so rather than
    cleaning up silently.
    """
    killed = []
    caps = getattr(driver, "capabilities", None) or {}
    browser_pid = caps.get("moz:processID") or 0
    service = getattr(driver, "service", None)
    service_proc = getattr(service, "process", None)
    service_pid = getattr(service_proc, "pid", 0) or 0

    with contextlib.suppress(Exception):
        driver.quit()

    for pid in (browser_pid, service_pid):
        if pid and _pid_alive(pid):
            _kill(pid)
            killed.append(pid)
    return killed
