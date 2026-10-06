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
import socket
import threading
import sys
from http.server import ThreadingHTTPServer
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
    if not wanted() or kind not in chosen():
        return NOT_INSTALLED
    for candidate in where["paths"]:
        if candidate and Path(candidate).is_file():
            return candidate
    for name in where["which"]:
        found = shutil.which(name)
        if found:
            return found
    return NOT_INSTALLED


#: Set to "off" to skip every browser test in this process.
SWITCH = "WD_BROWSER_TESTS"


def wanted() -> bool:
    """False only when `WD_BROWSER_TESTS=off`.

    CI runs four jobs - Windows and macOS, Python 3.10 and 3.14 - and the
    browser tests drove Firefox, Chrome and Edge in all four. They check
    what a page does in a browser, which does not change with the Python
    running the harness, so three of those four runs repeated the fourth
    and made every job minutes longer. `tests.yml` turns them off everywhere
    but one job, and `test_ci_runs_the_browser_tests` holds that exactly one
    job still runs them.

    Answering through `find` means every existing skip guard - they all ask
    whether the binary exists - skips with no change of its own. On a laptop
    nothing sets the variable, so they run wherever a browser is installed,
    as before.
    """
    return os.environ.get(SWITCH, "").strip().lower() != "off"


#: Comma-separated browsers this process may drive, e.g. "firefox". Unset
#: means all three.
ONLY = "WD_BROWSERS"


def chosen() -> set:
    """The browsers `WD_BROWSERS` allows - all three when it is unset.

    CI gives each browser a job of its own, so each one's tests run once and
    none of them competes with the rest of the suite for cores. Answering
    through `find`, like the on/off switch above, means every existing skip
    guard honours it without a change of its own.
    """
    raw = os.environ.get(ONLY, "").strip().lower()
    if not raw:
        return set(_WHERE)
    return {k.strip() for k in raw.split(",") if k.strip()}


def installed(kind: str) -> bool:
    return find(kind) != NOT_INSTALLED


#: Where macOS keeps Safari's WebDriver. Safari has no binary to point a
#: driver at and no headless mode - `safaridriver` drives the one installed
#: Safari in the logged-in desktop session - so it does not fit `_WHERE`.
SAFARIDRIVER = "/usr/bin/safaridriver"


def safari_requested() -> bool:
    """True only when `WD_BROWSERS` names Safari.

    Opt-in, never a default. A laptop with no `WD_BROWSERS` should not have a
    Safari window appear in the middle of the suite, and Safari has no
    headless mode. When it is asked for, `triple()` lists it as a fourth
    browser and every module that builds its drivers from that list drives it
    through `safari_driver()`. A module that does not know the name must not
    be handed it: each one's `_driver` used to fall through to Edge for any
    kind it did not recognise, which would have launched Edge under Safari's
    name.
    """
    if not wanted():
        return False
    raw = os.environ.get(ONLY, "").strip().lower()
    return "safari" in {k.strip() for k in raw.split(",")}


def safari_available() -> bool:
    """Requested, on a Mac, and `safaridriver` is there."""
    return (safari_requested() and sys.platform == "darwin"
            and Path(SAFARIDRIVER).is_file())


def available() -> list:
    """Which browsers this machine can actually drive: the three, and Safari
    when the run asked for it and it can be driven."""
    have = [k for k in ("firefox", "chrome", "edge") if installed(k)]
    return have + ["safari"] if safari_available() else have


def triple() -> list:
    """`[(kind, binary), ...]` in the order the suite has always used.

    Every browser is listed whether or not it is present - the tests skip on
    a binary that does not exist, and returning only what is installed would
    silently shrink the matrix instead of reporting a gap.

    A run that asked for Safari (`WD_BROWSERS=safari`) gets a fourth entry,
    `("safari", <safaridriver>)`, or `NOT_INSTALLED` where it cannot be
    driven. Any other run gets exactly the three it always did.
    """
    pairs = [(k, find(k)) for k in ("firefox", "chrome", "edge")]
    if safari_requested():
        pairs.append(("safari", SAFARIDRIVER if safari_available()
                      else NOT_INSTALLED))
    return pairs


#: Browser modules the Safari job does not run, and why. Every entry has to
#: say why in a sentence; `scripts/run_tests.py` prints each one so the list is
#: read in the CI transcript rather than found in this file, and
#: `tests/test_ci_splits_and_parallelises_the_suite.py` fails on an entry that
#: names no module or gives no reason. Not a place to put a test that fails.
SAFARI_NOT_APPLICABLE = {
    "test_cloud_name_colours": "drives Firefox only, by construction",
    "test_dev_mode_can_be_left": "drives Firefox only, and ends on a Firefox print",
    "test_dev_toolbar_does_not_print": "reads Firefox's print pipeline",
    "test_modal_buttons_have_room": "drives Firefox only, by construction",
    "test_nothing_is_left_running": "audits how Firefox is stopped",
    "test_report_first_sheet_orientation_browser":
        "prints through WebDriver's Print Page command, which safaridriver does not implement",
    "test_rf_design_review_browser":
        "prints through WebDriver's Print Page command, which safaridriver does not implement",
}

#: Set once the first Safari session has been made.
_SAFARI_SELECT_PATCHED = False

#: Safari's WebDriver answers a click on an <option> with "element not
#: interactable", so `Select(...).select_by_value()` - used all over this
#: suite - fails there on every call. The choice is made the way a page hears
#: it instead: the option marked selected and `input` / `change` fired on the
#: <select>.
_PICK_OPTION_JS = (
    "var s = arguments[0], o = arguments[1]; o.selected = true;"
    "s.dispatchEvent(new Event('input', { bubbles: true }));"
    "s.dispatchEvent(new Event('change', { bubbles: true }));")


def _patch_select_for_safari() -> None:
    """Make `Select` choose by script, for this process, once.

    Only ever applied in a run that asked for Safari - `safari_driver` is the
    only caller - and that run drives no other browser, so Firefox, Chrome and
    Edge keep a genuine click.
    """
    global _SAFARI_SELECT_PATCHED
    if _SAFARI_SELECT_PATCHED:
        return
    from selenium.webdriver.support.select import Select

    def _set_selected(self, option, *_ignored):
        if not option.is_selected():
            self._el.parent.execute_script(_PICK_OPTION_JS, self._el, option)

    Select._set_selected = _set_selected
    _SAFARI_SELECT_PATCHED = True


def select_all():
    """The keys that select all the text in a field: Cmd+A on a Mac, Ctrl+A
    elsewhere.

    On macOS, Ctrl+A in a text field moves the caret to the start of the line,
    so `send_keys(Keys.CONTROL, "a")` followed by typing inserts in front of
    what was there. Three AP Labeler tests did, in Safari - `101` typed into a
    box holding `1` read `1011` - and looked like a fault in the page.
    """
    from selenium.webdriver.common.keys import Keys
    return (Keys.COMMAND if sys.platform == "darwin" else Keys.CONTROL, "a")


#: Puts files into a file input the way a person's choice does: the input's
#: `files` set and `input` / `change` fired. Works on an input that is hidden,
#: which is how every tool here styles its own.
_UPLOAD_JS = (
    "var el = arguments[0], files = arguments[1];"
    "var dt = new DataTransfer();"
    "files.forEach(function (f) {"
    "  var bytes = Uint8Array.from(atob(f.b64), function (c) { return c.charCodeAt(0); });"
    "  dt.items.add(new File([bytes], f.name, { type: f.type }));"
    "});"
    "el.files = dt.files;"
    "el.dispatchEvent(new Event('input', { bubbles: true }));"
    "el.dispatchEvent(new Event('change', { bubbles: true }));")


def upload_by_script(element, paths) -> None:
    """Hand `paths` to a file input without the driver's file chooser.

    Safari's `send_keys(path)` on a file input is accepted and delivers
    nothing: the page never sees a change, so every test that opens a project
    that way waited out its timeout on a page that had nothing loaded - eleven
    modules on the first full Safari run.
    """
    import base64
    import mimetypes
    files = []
    for path in paths:
        path = Path(path)
        files.append({
            "name": path.name,
            "type": mimetypes.guess_type(path.name)[0] or "application/octet-stream",
            "b64": base64.b64encode(path.read_bytes()).decode("ascii")})
    element.parent.execute_script(_UPLOAD_JS, element, files)


#: Set once the first Safari session has been made.
_SAFARI_SEND_KEYS_PATCHED = False


def _patch_send_keys_for_safari() -> None:
    """Route `send_keys(path)` on a file input through `upload_by_script`.

    Only ever applied in a run that asked for Safari, which drives no other
    browser, so Firefox, Chrome and Edge keep their own file handling.
    """
    global _SAFARI_SEND_KEYS_PATCHED
    if _SAFARI_SEND_KEYS_PATCHED:
        return
    from selenium.webdriver.remote.webelement import WebElement
    original = WebElement.send_keys

    def send_keys(self, *value):
        if (self.tag_name.lower() == "input"
                and (self.get_attribute("type") or "").lower() == "file"):
            upload_by_script(self, [p for p in "".join(map(str, value)).split("\n") if p])
            return None
        return original(self, *value)

    WebElement.send_keys = send_keys
    _SAFARI_SEND_KEYS_PATCHED = True


def make_driver(kind, binary):
    """A driver for `kind`, or None when it will not start. Headless where the
    browser can be; Safari takes no options. For tests written from here on -
    the older modules each carry their own copy of this."""
    try:
        from selenium import webdriver
        from selenium.common.exceptions import WebDriverException
    except ImportError:
        return None
    if kind == "safari":
        return safari_driver()
    if not Path(binary).exists():
        return None
    try:
        if kind == "firefox":
            o = webdriver.FirefoxOptions()
            o.binary_location = binary
            o.add_argument("-headless")
            return webdriver.Firefox(options=o)
        if kind == "chrome":
            o = webdriver.ChromeOptions()
            o.binary_location = binary
            o.add_argument("--headless=new")
            o.add_argument("--no-sandbox")
            return webdriver.Chrome(options=o)
        o = webdriver.EdgeOptions()
        o.binary_location = binary
        o.add_argument("--headless=new")
        return webdriver.Edge(options=o)
    except (WebDriverException, OSError):
        return None


def safari_driver():
    """A Safari session, or None when it will not start.

    No options: Safari takes no binary path, cannot be headless, and runs as
    the logged-in user on the runner's desktop. One session at a time per
    machine - which is why the Safari job runs its modules one after another.
    """
    try:
        from selenium import webdriver
        from selenium.common.exceptions import WebDriverException
    except ImportError:
        return None
    _patch_select_for_safari()
    _patch_send_keys_for_safari()
    try:
        return webdriver.Safari()
    except (WebDriverException, OSError) as exc:
        print("safaridriver would not start a session: %s"
              % str(exc).strip().splitlines()[0][:200], file=sys.stderr)
        return None


def on_ci() -> bool:
    """GitHub sets `CI=true`; so does most of the rest of the world."""
    return os.environ.get("CI", "").lower() in ("1", "true", "yes")


def why_missing() -> str:
    """A sentence for a skip message, naming what was looked for."""
    if not wanted():
        return ("browser tests are switched off in this run (%s=off); "
                "CI runs them in a job of their own" % SWITCH)
    if safari_requested() and not safari_available():
        return ("Safari was asked for (%s) but %s is not here - Safari can "
                "only be driven on macOS, after `sudo safaridriver --enable`"
                % (ONLY, SAFARIDRIVER))
    if set(_WHERE) - chosen():
        return ("this run drives only %s (%s); the other browsers are "
                "tested in their own jobs"
                % (", ".join(sorted(chosen() & set(_WHERE))) or "no browser",
                   ONLY))
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


def _contain_descendants():
    """Windows: end everything this process starts when this process ends.

    `shut_down` only helps if it runs. When the test process itself dies - the
    runner stops a module that ran past its timeout, a crash, a closed console -
    Windows kills that one process and nothing under it. geckodriver and the
    Firefox it launched carry on with no parent, holding their memory and their
    working directory: a worktree whose folder then cannot be deleted, because
    an invisible Firefox is sitting in it. Found on 2026-09-29 as eleven
    processes started with ``--marionette`` and a throwaway profile, whose
    geckodriver was long gone.

    A job object with ``KILL_ON_JOB_CLOSE`` closes that. This process joins it
    at import, every process it starts from then on inherits it, and when this
    process ends by any route the handle closes and the kernel ends the rest.
    ``BREAKAWAY_OK`` leaves a process that explicitly asks to escape free to do
    so; nothing in this repository does.

    Returns the job handle, or None where this does not apply or the process
    could not be placed in a job. Failing here is not worth failing a test run
    over: the suite behaves exactly as it did before.
    """
    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class _Basic(ctypes.Structure):
        _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                    ("PerJobUserTimeLimit", ctypes.c_int64),
                    ("LimitFlags", wintypes.DWORD),
                    ("MinimumWorkingSetSize", ctypes.c_size_t),
                    ("MaximumWorkingSetSize", ctypes.c_size_t),
                    ("ActiveProcessLimit", wintypes.DWORD),
                    ("Affinity", ctypes.c_size_t),
                    ("PriorityClass", wintypes.DWORD),
                    ("SchedulingClass", wintypes.DWORD)]

    class _Io(ctypes.Structure):
        _fields_ = [(n, ctypes.c_uint64) for n in (
            "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
            "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

    class _Extended(ctypes.Structure):
        _fields_ = [("BasicLimitInformation", _Basic),
                    ("IoInfo", _Io),
                    ("ProcessMemoryLimit", ctypes.c_size_t),
                    ("JobMemoryLimit", ctypes.c_size_t),
                    ("PeakProcessMemoryUsed", ctypes.c_size_t),
                    ("PeakJobMemoryUsed", ctypes.c_size_t)]

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateJobObjectW.restype = wintypes.HANDLE
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.SetInformationJobObject.argtypes = (
        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
    kernel32.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)

    job = kernel32.CreateJobObjectW(None, None)
    if not job:
        return None
    info = _Extended()
    info.BasicLimitInformation.LimitFlags = 0x2000 | 0x800  # KILL_ON_JOB_CLOSE | BREAKAWAY_OK
    extended_limit_information = 9
    if not kernel32.SetInformationJobObject(job, extended_limit_information,
                                            ctypes.byref(info), ctypes.sizeof(info)):
        kernel32.CloseHandle(job)
        return None
    if not kernel32.AssignProcessToJobObject(job, kernel32.GetCurrentProcess()):
        kernel32.CloseHandle(job)
        return None
    return job


#: Held for the life of the process and never closed by hand: closing it is
#: what ends everything the process started, and that happens at exit.
_JOB = _contain_descendants()


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



class ExclusiveServer(ThreadingHTTPServer):
    """A stub server on a port nobody else can be on.

    Every browser module used to choose its port by probing upward from a
    hint (8791, 8834, 8841, 8847, 8911, 8931, 8951, 8967...) and then binding
    it. The ranges overlap, four modules run at once in CI, and a probe only
    shows that a port is free at that instant - so two modules could pick the
    same one. `http.server` sets SO_REUSEADDR, and on Windows that lets both
    bind it. The page's requests then reach either stub; answered by the
    wrong one, the page under test is not the page the test wrote. It surfaced
    as unrelated, rotating failures: Labeler floors that never loaded in Edge
    and then Chrome, Cloud menu items "drawn" nowhere.

    Bind port 0 and read `server_address[1]`: the OS assigns a free port
    atomically, and with no reuse a port in use cannot be taken.
    `tests/test_every_stub_server_has_a_port_of_its_own.py` holds every
    module to it.
    """
    allow_reuse_address = False

#: How long to wait for a `serve_forever` loop to acknowledge a shutdown
#: before giving up on it and closing the socket anyway.
SHUTDOWN_WAIT_S = 5.0


def _swallow(fn):
    try:
        fn()
    except Exception:                                         # noqa: BLE001
        pass


def stop_server(server) -> bool:
    """`shutdown()` then `server_close()`, each on its own, and report.

    Seven suites did this instead:

        with contextlib.suppress(Exception):
            server.shutdown()
            server.server_close()

    Both calls are inside one `suppress`, so a `shutdown()` that raises takes
    `server_close()` with it - and `server_close()` is the one that releases
    the listening socket. The failure is swallowed, the suite exits reporting
    nothing, and the port stays held for whoever runs next. It is the same
    shape as the browser teardown that left three Firefoxes behind: cleanup
    written so that failing and succeeding look identical.

    They are separate here, `server_close()` runs whatever `shutdown()` did,
    and the caller is told whether the port actually came free.
    """
    ok = True

    # `shutdown()` blocks until the `serve_forever` loop acknowledges it, and
    # a server that was built but never served has no loop to acknowledge
    # anything - so it waits for ever. A teardown that can hang is worse than
    # one that can fail: a failure is visible and a hang looks like a busy
    # suite. Bounded, in a thread, and then the socket is closed regardless.
    shutdown = getattr(server, "shutdown", None)
    if shutdown is not None:
        worker = threading.Thread(target=_swallow, args=(shutdown,), daemon=True)
        worker.start()
        worker.join(SHUTDOWN_WAIT_S)
        # A shutdown nobody acknowledged is not a failure. A server built but
        # never served has no loop to answer, and the only thing that decides
        # whether this worked is whether the port came free - which is asked
        # below, of the address, rather than inferred from which methods were
        # called. Inferring it from the calls is what the suppressed version
        # did.

    close = getattr(server, "server_close", None)
    if close is not None:
        try:
            close()
        except Exception:                                     # noqa: BLE001
            ok = False

    return ok and not port_held(server)


def port_held(server) -> bool:
    """Is the socket this server was listening on still bound?

    Asked of the address rather than of the object, because "we called the
    right methods" is what the suppressed version also believed.
    """
    address = getattr(server, "server_address", None)
    if not address:
        return False
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # Deliberately no SO_REUSEADDR. On Windows it lets a second socket
        # bind an address that is still in use, so the probe would report
        # every port free - including the ones this is looking for.
        probe.bind(address)
    except OSError:
        return True
    finally:
        probe.close()
    return False
