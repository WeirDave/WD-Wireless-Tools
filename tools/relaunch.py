"""Starting the tool while it is already running opens a tab; it kills nothing.

Both launchers used to stop whatever ``server.py`` held the port, every time.
Double-clicking the launcher a second time - or clicking it while an upload,
a trim or a sync was running - therefore killed the work that was in progress,
and a plain "open it again" cost the full start-up.

    python -m tools.relaunch <port>

asks the server already on the port (``/api/version``) and exits with:

* **0** - that server is this app, current, and not about to restart. A browser
  tab has been opened on it and the launcher has nothing left to do.
* **1** - nothing to attach to: no server, something else on the port, a
  server running older code than is on disk, or one that is restarting.
  The launcher goes on to replace it exactly as it always did.
* **2** - the server runs older code than is on disk **and is in the middle of
  work**. Replacing it would throw that work away, so the launcher stops and
  says why. ``WD_FORCE_RESTART=1`` overrides, for a server that is stuck and
  will never finish.

**The server decides, not the launcher.** ``/api/version`` reports ``busy``,
``restarting`` and ``restartReady`` (the code on disk has moved on since this
process started); the launcher only reads them. A restart the app starts
itself marks ``restarting`` before it launches the new window, which is what
stops that new launcher from "attaching" to the process that is about to exit.

**Anything unexpected is exit 1.** A launcher that cannot tell must behave as
it did before this existed, so every failure here - no network stack, a
timeout, a body that is not JSON - falls through to the old path.
"""
from __future__ import annotations

import json
import os
import sys
import urllib.request
import webbrowser

ATTACH = 0
REPLACE = 1
WAIT = 2

PROBE_TIMEOUT_S = 2.0
DEFAULT_PORT = 8675


def probe(port: int, timeout: float = PROBE_TIMEOUT_S):
    """What the server on this port says about itself, or None.

    Proxies are ignored on purpose: this is a loopback request, and a
    corporate proxy answering it would be answering for something else.
    """
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(f"http://127.0.0.1:{int(port)}/api/version",
                         timeout=timeout) as resp:
            info = json.loads(resp.read(65536).decode("utf-8"))
    except Exception:
        return None
    return info if isinstance(info, dict) else None


def is_this_app(info) -> bool:
    versions = info.get("versions") if isinstance(info, dict) else None
    return isinstance(versions, dict) and bool(versions.get("suite"))


def decide(info, force: bool = False):
    """(exit code, sentence) for what the server on the port reported."""
    if force:
        return REPLACE, ""
    if not is_this_app(info):
        return REPLACE, ""
    if info.get("restarting"):
        return REPLACE, ""
    if info.get("restartReady"):
        if info.get("busy"):
            return WAIT, (
                "WD Wireless Tools is running older code than is installed, and "
                "it is in the middle of something (an upload, a trim or a sync). "
                "Starting a new copy now would stop that work.\n"
                "Wait for it to finish, then start this launcher again. If the "
                "server is stuck, set WD_FORCE_RESTART=1 and start it again.")
        return REPLACE, ""
    return ATTACH, ""


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        port = int(argv[0]) if argv else int(os.environ.get("PORT") or DEFAULT_PORT)
    except ValueError:
        return REPLACE
    force = os.environ.get("WD_FORCE_RESTART") == "1"
    code, why = decide(probe(port), force=force)
    if why:
        print()
        print(" " + why.replace("\n", "\n "))
        print()
    if code == ATTACH:
        try:
            webbrowser.open(f"http://localhost:{port}/")
        except Exception:
            return REPLACE
    return code


if __name__ == "__main__":
    sys.exit(main())
