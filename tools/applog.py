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

import datetime as _dt
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

# He asked how large it can get, and "it cannot exceed 10 MB" is a better
# answer than an estimate - so both limits are enforced rather than hoped for.
#
# Seven days because that is what he asked for, and because "it happened
# yesterday" should be answerable by opening yesterday's file. Rotation is by
# day rather than by size for the same reason: a size-rolled file tells you
# nothing about when it covers.
RETAIN_DAYS = 7
MAX_FILE_BYTES = 2_000_000      # one day's file, before it rolls to a part
MAX_TOTAL_BYTES = 8_000_000     # everything kept, pruned oldest-first
# Worst case is one live file that has not yet rolled on top of a pruned set,
# so the true ceiling is MAX_TOTAL_BYTES + MAX_FILE_BYTES.
HARD_CEILING_BYTES = MAX_TOTAL_BYTES + MAX_FILE_BYTES

_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"

_installed = False
_install_lock = threading.Lock()


def log_dir() -> Path:
    return user_dir() / LOG_DIR_NAME


def log_path() -> Path:
    return log_dir() / LOG_FILE_NAME


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


class DailyCappedFileHandler(logging.FileHandler):
    """A day per file, seven days kept, and a ceiling it cannot pass.

    **It appends, and it never truncates on startup.** That is the whole point
    of the class: a handler that opened in "w" would have destroyed the only
    copy of a fault the moment he restarted to see whether it recurred, which
    is exactly the sequence that lost one.

    The live file always has the same name, so the path shown in About stays
    true. Yesterday's is renamed with its own date beside it.
    """

    def __init__(self, path, retain_days: int = RETAIN_DAYS,
                 max_file_bytes: int = MAX_FILE_BYTES,
                 max_total_bytes: int = MAX_TOTAL_BYTES):
        self._live = Path(path)
        self._retain_days = retain_days
        self._max_file_bytes = max_file_bytes
        self._max_total_bytes = max_total_bytes
        self._day = self._today()
        self._live.parent.mkdir(parents=True, exist_ok=True)
        # mode "a": the existing file is continued, never replaced.
        super().__init__(str(self._live), mode="a", encoding="utf-8",
                         delay=True)

    # -- naming ------------------------------------------------------------

    @staticmethod
    def _today() -> str:
        return _dt.date.today().isoformat()

    def _archive_name(self, day: str) -> Path:
        stem = self._live.stem
        candidate = self._live.with_name(f"{stem}.{day}.log")
        part = 1
        while candidate.exists():
            candidate = self._live.with_name(f"{stem}.{day}.{part}.log")
            part += 1
        return candidate

    def archives(self) -> list[Path]:
        stem = self._live.stem
        return sorted(
            (p for p in self._live.parent.glob(f"{stem}.*.log")
             if p != self._live),
            key=lambda p: p.name)

    # -- rotation ----------------------------------------------------------

    def emit(self, record):
        try:
            self._roll_if_due()
        except Exception:          # rotation must never lose the record
            pass
        super().emit(record)

    def _roll_if_due(self) -> None:
        today = self._today()
        try:
            size = self._live.stat().st_size
        except OSError:
            size = 0
        if today == self._day and size < self._max_file_bytes:
            return
        self._roll(today)

    def _roll(self, today: str) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None
        if self._live.exists():
            try:
                self._live.rename(self._archive_name(self._day))
            except OSError:
                return             # keep writing where we are rather than lose it
        self._day = today
        self.prune()

    def prune(self) -> None:
        """Drop anything past the window, then anything past the ceiling."""
        cutoff = _dt.date.today() - _dt.timedelta(days=self._retain_days)
        kept = []
        for path in self.archives():
            day = _day_of(path)
            if day is not None and day < cutoff:
                _unlink(path)
            else:
                kept.append(path)

        def total() -> int:
            files = kept + ([self._live] if self._live.exists() else [])
            out = 0
            for f in files:
                try:
                    out += f.stat().st_size
                except OSError:
                    pass
            return out

        while kept and total() > self._max_total_bytes:
            _unlink(kept.pop(0))


def _day_of(path: Path):
    """The date in `<stem>.YYYY-MM-DD[.n].log`, or None if it has none."""
    for part in path.name.split("."):
        try:
            return _dt.date.fromisoformat(part)
        except ValueError:
            continue
    return None


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _file_handler() -> logging.Handler:
    log_dir().mkdir(parents=True, exist_ok=True)
    handler = DailyCappedFileHandler(log_path())
    handler.setFormatter(logging.Formatter(_FORMAT))
    handler.setLevel(logging.INFO)
    handler.prune()
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
        # Ours at INFO, everything else at WARNING. A file dominated by
        # library chatter rotates the useful part out early, and the useful
        # part is the reason the file exists. `waitress` does not log a line
        # per request by default, and the queue-depth noise it does produce is
        # already filtered in server.py.
        root.setLevel(logging.WARNING)
        root.addHandler(handler)
        get_logger().setLevel(logging.INFO)

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
