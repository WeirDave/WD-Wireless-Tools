"""A fault has to survive the window being closed.

Something went wrong in his terminal, it printed a wall of traceback, and by
the time anyone could look the window had been closed and the machine was
three hours away. One chance to see it, and it was missed. That is the whole
reason this file exists: the console is not a record, it is a window somebody
closes.

So every unhandled exception lands in a rotating file under the user data
directory - the same `~/.wd_wireless_tools` the settings and templates live
in, because a second location for state is its own bug - and the console gets
one calm line pointing at it.

**Background threads need their own hook.** `sys.excepthook` never sees them:
a thread that raises prints its traceback through `threading.excepthook` and
the process carries on as if nothing happened, which is precisely the failure
that leaves no trace. Both are installed here.

**This file is local and stays local.** It records real paths, real filenames
and the machine's own hostname, which is exactly the material rule zero is
about. It is gitignored, it is not in the release payload, and it must never
become a test fixture or be uploaded anywhere. Reading it is something he does
on his own machine and pastes from deliberately.
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import sys
import threading
from pathlib import Path

from tools.user_dir import user_dir

LOGGER_NAME = "wd"
LOG_DIR_NAME = "logs"
LOG_FILE_NAME = "wd-wireless-tools.log"

# Small enough that he can open it, big enough to hold a session's worth of
# noise. Four files total, so the ceiling is about 4 MB however long it runs.
MAX_BYTES = 1_000_000
BACKUP_COUNT = 3

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

_installed = False
_install_lock = threading.Lock()


def log_dir() -> Path:
    return user_dir() / LOG_DIR_NAME


def log_path() -> Path:
    return log_dir() / LOG_FILE_NAME


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def _file_handler() -> logging.Handler:
    log_dir().mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        str(log_path()), maxBytes=MAX_BYTES, backupCount=BACKUP_COUNT,
        encoding="utf-8", delay=True,
    )
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler.setLevel(logging.INFO)
    return handler


def install(quiet_console: bool = True,
            app_version: str | None = None) -> Path | None:
    """Start writing to the log file. Returns the path, or None if it cannot.

    Never raises. A read-only home directory or a full disk is a reason to
    carry on without a log, not a reason to refuse to start the app - the
    logging exists to make failures visible, and taking the product down to
    achieve that would be an odd trade.
    """
    global _installed
    with _install_lock:
        if _installed:
            return log_path()
        try:
            handler = _file_handler()
        except OSError:
            return None

        root = logging.getLogger()
        root.setLevel(logging.INFO)
        root.addHandler(handler)

        _install_excepthooks(quiet_console)
        _installed = True
        _note_start(app_version)
        return log_path()


def _note_start(app_version: str | None) -> None:
    """One line per run, so the file exists before anything goes wrong.

    Two reasons it is not just noise. A log that is only created by a failure
    is a path in the About panel pointing at nothing, and "send me the log" is
    then an instruction that fails for the person following it. And the first
    question asked of any report is which version was running - so the answer
    is written down at the top of every run rather than reconstructed later.
    """
    try:
        get_logger().info(
            "started - version %s, python %s, pid %s",
            app_version or "unknown",
            sys.version.split()[0],
            os.getpid(),
        )
    except Exception:
        pass


def _install_excepthooks(quiet_console: bool) -> None:
    log = get_logger()

    previous = sys.excepthook

    def on_uncaught(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            previous(exc_type, exc, tb)
            return
        log.critical("unhandled exception", exc_info=(exc_type, exc, tb))
        if quiet_console:
            console(f"{exc_type.__name__}: {exc}")
        else:
            previous(exc_type, exc, tb)

    sys.excepthook = on_uncaught

    def on_thread(args):
        # A raising background thread is the one that leaves no trace: its
        # traceback goes to stderr and the process keeps serving, so the app
        # looks healthy and the evidence scrolls away.
        if args.exc_type is SystemExit:
            return
        log.critical("unhandled exception in thread %s",
                     getattr(args.thread, "name", "?"),
                     exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
        if quiet_console:
            console(f"{args.exc_type.__name__}: {args.exc_value}")

    threading.excepthook = on_thread


def console(summary: str) -> None:
    """One short line on the terminal, pointing at the file for the rest.

    The contract for anything the user is meant to read at a terminal: what
    happened, in a sentence, and where the detail is. Not a stack.
    """
    try:
        print(f"\n  ! {summary}\n    Details: {log_path()}\n", flush=True)
    except Exception:
        pass


def note_failure(what: str, exc: BaseException, *, level: int = logging.ERROR,
                 to_console: bool = False) -> None:
    """Record a failure that the app is choosing to carry on from.

    `what` is the operation in plain words - "update check" - so a line of
    the log reads as a sentence rather than as a symbol name.
    """
    get_logger().log(level, "%s failed: %s", what, exc, exc_info=exc)
    if to_console:
        console(f"{what} failed: {exc}")
