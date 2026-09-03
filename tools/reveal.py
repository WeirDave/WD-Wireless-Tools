"""
WD Wireless Tools — reveal a file or folder in the host's file browser.

Opening the containing folder with the file highlighted is what people mean by
"show me where it went", so that is the default wherever the platform supports
it: ``explorer /select,`` on Windows, ``open -R`` on macOS. Linux has no
standard "select this file" verb, so it falls back to opening the folder.

Two details that are easy to get wrong and are the reason this lives in one
place rather than being written per tool:

* Explorer parses ``/select,<path>`` as a **single** token. Passing "/select,"
  and the path as separate argv entries silently drops the path and Explorer
  opens the default folder instead — the file is never highlighted.
* Nothing here takes a path from the browser. Callers pass a path the server
  already knows, and pass it as a list rather than through a shell, so a client
  cannot smuggle arguments into a command line.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# Windows: don't flash a console window from a windowed launcher.
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def reveal(path) -> dict:
    """Open *path* in the file browser, highlighting it when possible.

    Returns ``{"ok": True}`` or ``{"error": ...}``. Callers treat a failure as
    cosmetic: the work that produced the file already succeeded.
    """
    try:
        p = Path(path)
        if not p.exists():
            return {"error": "Path not found"}
        p = p.resolve()

        if sys.platform == "win32":
            if p.is_dir():
                os.startfile(str(p))  # noqa: S606 - documented Windows API
            else:
                # One token. See the note above.
                subprocess.Popen(["explorer", "/select," + str(p)],
                                 creationflags=_NO_WINDOW)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(p)] if p.is_dir()
                             else ["open", "-R", str(p)])
        else:
            target = str(p if p.is_dir() else p.parent)
            subprocess.Popen(["xdg-open", target])
        return {"ok": True}
    except Exception as exc:  # pragma: no cover - platform dependent
        return {"error": str(exc)}
