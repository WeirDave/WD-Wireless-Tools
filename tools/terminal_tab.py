"""Open the launcher in a Windows Terminal tab instead of a window of its own.

`Start WD Wireless Tools.bat` calls this before it does anything else:

    python -m tools.terminal_tab "<path to the .bat>"

Exit code 0 means "handed off - a tab is running the launcher, this window has
nothing left to do"; 1 means "run here as usual". Nothing is printed on the way
to either, so the launcher stays quiet when it has nothing to say.

**What it can and cannot do.** Windows has no way to move a process into a
shell that is already running, so "attach to the open PowerShell" is not on
offer. What exists is a new tab in a Windows Terminal window that is already
open, or a new window when none is.

**`wt.exe -w 0` is not "a new window when there is none".** It was assumed to
be, and on a real machine it opened nothing: Windows Terminal reported
success, no tab appeared, the launcher's own window closed behind it, and the
app never started. So the window is chosen by looking: `-w 0` (the most
recent window) only while a Windows Terminal process is running, `-w -1` (a
new window) otherwise.

**A tab that was asked for is not a tab that opened**, so the launcher waits
for the tab to say so. The tab runs the launcher with `--in-tab`, and the
launcher's first act there is `python -m tools.terminal_tab --ack`, which
writes a flag file. Nothing seen within `ACK_WAIT_S` means the tab did not
come up: the other window choice is tried once, and if that fails too the
launcher runs in the window it is already in. A launcher that cannot open its
tab starts anyway, in plain sight, instead of vanishing.

* already inside Windows Terminal (`WT_SESSION`) - run in this tab. This is
  also what happens when the launcher is typed into an open PowerShell tab.
* inside another terminal host (VS Code sets `TERM_PROGRAM`) - run there; the
  person chose that terminal.
* the person turned it off (Settings -> General), or `wt.exe` is not installed,
  or this is not Windows - run here.
* `--in-tab`, which the tab passes back to the launcher, is a second guard
  against launching a tab from inside the tab it just opened.

macOS is untouched: `.command` already opens Terminal.app.
"""
from __future__ import annotations

import ntpath
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

TAB_TITLE = "WD Wireless Tools"

# Handed to the launcher by the tab it opens, so a launcher that cannot see
# WT_SESSION still never opens a second tab from inside the first.
IN_TAB_FLAG = "--in-tab"

# The server exits with this on a restart that has opened its replacement tab.
# The launcher turns it into a clean exit, so the old tab closes by itself:
# Windows Terminal leaves a tab open after a non-zero exit, which is what
# killing the launcher's cmd.exe produces.
RESTART_EXIT_CODE = 75

HANDED_OFF = 0
RUN_HERE = 1

# What the tab runs first, to say it came up. See the module docstring.
ACK_FLAG = "--ack"
ACK_NAME = "tab_started.flag"
ACK_WAIT_S = 15.0
ACK_POLL_S = 0.2

# `-w 0` is the most recently used window; `-w -1` is a new one.
EXISTING_WINDOW = "0"
NEW_WINDOW = "-1"


def tab_enabled(settings=None) -> bool:
    """The `global.terminal_tab` preference. On unless it is explicitly off.

    Any failure to read settings means on: an unreadable file must not be the
    reason the launcher behaves differently from the one every other
    install has.
    """
    try:
        if settings is None:
            from tools import settings as settings_module
            settings = settings_module.load_settings()
        return (settings.get("global") or {}).get("terminal_tab") is not False
    except Exception:
        return True


def find_wt(which=shutil.which):
    return which("wt.exe") or which("wt")


def already_in_a_terminal(env) -> bool:
    return bool(env.get("WT_SESSION") or env.get("TERM_PROGRAM"))


def tab_command(wt: str, launcher: str, *, title: str = TAB_TITLE,
                window: str = EXISTING_WINDOW):
    """The argv that opens `launcher` in a new tab of window `window`.

    `window` is `-w`'s value: `0` the most recently used window, `-1` a new
    one. The tab runs `cmd /c`, so closing the launcher's last prompt closes
    the tab. `;` is Windows Terminal's own command separator and cannot be
    quoted for it through this route - `can_hand_off` refuses a path that has
    one.
    """
    return [
        wt, "-w", window, "new-tab",
        "--title", title, "--suppressApplicationTitle",
        "-d", ntpath.dirname(launcher) or ".",
        "cmd.exe", "/c", launcher, IN_TAB_FLAG,
    ]


def can_hand_off(launcher: str, *, os_name=None, env=None, which=shutil.which,
                 settings=None, argv=()) -> bool:
    os_name = os.name if os_name is None else os_name
    env = os.environ if env is None else env
    if os_name != "nt":
        return False
    if IN_TAB_FLAG in argv:
        return False
    if already_in_a_terminal(env):
        return False
    if ";" in launcher:
        return False
    if not tab_enabled(settings):
        return False
    return bool(find_wt(which))


def terminal_running(run=subprocess.run) -> bool:
    """Is a Windows Terminal process running, for any window or tab?

    `tasklist` rather than a process handle: it can see a terminal that was
    started elevated, which a handle cannot.
    """
    try:
        out = run(["tasklist", "/FI", "IMAGENAME eq WindowsTerminal.exe",
                   "/NH", "/FO", "CSV"], capture_output=True, text=True,
                  timeout=15)
    except (OSError, subprocess.SubprocessError):
        return False
    return "windowsterminal.exe" in (out.stdout or "").lower()


def ack_path() -> Path:
    from tools.user_dir import user_dir
    return user_dir() / ACK_NAME


def acknowledge() -> None:
    """Called from inside the tab: say that it came up."""
    path = ack_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(time.time()), encoding="utf-8")


def _clear_ack() -> None:
    try:
        ack_path().unlink()
    except FileNotFoundError:
        pass


def wait_for_ack(*, timeout: float = ACK_WAIT_S, sleep=time.sleep,
                 clock=time.monotonic) -> bool:
    deadline = clock() + timeout
    while True:
        if ack_path().exists():
            return True
        if clock() >= deadline:
            return False
        sleep(ACK_POLL_S)


def open_tab(launcher: str, *, popen=subprocess.Popen, which=shutil.which,
             running=terminal_running, window: str | None = None) -> bool:
    """Start the tab. False if Windows Terminal could not be started.

    This says the command was issued, not that a tab exists; see
    `open_confirmed_tab` for that.
    """
    wt = find_wt(which)
    if not wt:
        return False
    if window is None:
        window = EXISTING_WINDOW if running() else NEW_WINDOW
    try:
        popen(tab_command(wt, launcher, window=window), close_fds=True)
    except OSError as exc:
        _note_failure(exc)
        return False
    return True


def open_confirmed_tab(launcher: str, *, popen=subprocess.Popen,
                       which=shutil.which, running=terminal_running,
                       wait=wait_for_ack) -> bool:
    """Open the tab and wait for it to report that it is running.

    The window is chosen by whether a terminal is open. If the tab does not
    report, the other choice is tried once - a window that cannot be reached
    is the failure this exists for - and then the answer is False, which
    means "run in this window".
    """
    first = EXISTING_WINDOW if running() else NEW_WINDOW
    order = [first] + [w for w in (EXISTING_WINDOW, NEW_WINDOW) if w != first]
    for window in order:
        _clear_ack()
        if not open_tab(launcher, popen=popen, which=which, window=window):
            return False
        if wait():
            return True
    _note_failure(RuntimeError(
        "Windows Terminal was asked for a tab and none came up"))
    return False


def restart_in_tab(launcher: str, *, os_name=None, which=shutil.which,
                   popen=subprocess.Popen, settings=None,
                   running=terminal_running, wait=wait_for_ack) -> bool:
    """Open the restarted launcher in a tab; True if it did.

    Used by the server's restart, where the environment is the old server's
    and says nothing about whether *this* restart should be a tab - only the
    preference and the presence of `wt.exe` do.
    """
    os_name = os.name if os_name is None else os_name
    if os_name != "nt" or ";" in launcher or not tab_enabled(settings):
        return False
    return open_confirmed_tab(launcher, popen=popen, which=which,
                              running=running, wait=wait)


def _note_failure(exc: BaseException) -> None:
    try:
        from tools import applog
        applog.note_failure("opening a Windows Terminal tab", exc,
                            to_console=True)
    except Exception:
        pass


def main(argv=None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if ACK_FLAG in args:
        acknowledge()
        return HANDED_OFF
    launcher = next((a for a in args if a != IN_TAB_FLAG), "")
    if not launcher:
        return RUN_HERE
    if not can_hand_off(launcher, argv=args):
        return RUN_HERE
    return HANDED_OFF if open_confirmed_tab(launcher) else RUN_HERE


if __name__ == "__main__":
    sys.exit(main())
