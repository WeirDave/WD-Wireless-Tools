r"""
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
* **And the quoting has to be done by hand, because the obvious fix is wrong
  on every path with a space in it.** Handing Popen the list
  ``["explorer", "/select,C:\...\Ekahau AI Pro Projects\x.esx"]`` looks
  correct and is not: Windows has no argv, so Python joins the list with
  ``list2cmdline``, which sees a space inside that one token and wraps *the
  whole thing* in quotes —

      explorer "/select,C:\Users\...\Ekahau AI Pro Projects\x.esx"

  Explorer does not recognise a switch that begins inside a quote, so it
  ignores it and opens its default folder. Reported as "the Show button just
  takes you to the parent directory of Documents", which is exactly what that
  looks like. It works perfectly on a path with no spaces, which is why it
  survived every check made here.

  So on Windows the command line is built as a **string**, with the quotes
  around the path only, and Popen hands it to CreateProcess untouched.
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


def windows_select_command(path) -> str:
    r"""The command line that highlights `path` in Explorer.

    Built here, as one string, rather than left to `list2cmdline` - see the
    module docstring for what that does to a path with a space in it. The
    quotes go around the path and nothing else:

        explorer /select,"C:\\Users\\me\\Ekahau AI Pro Projects\\x.esx"

    Separate from `reveal` so the shape can be asserted on any platform. The
    fault it fixes was invisible to a test that only ran the call.
    """
    return 'explorer /select,"%s"' % str(path)


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
                # A string, not a list. See the note above.
                subprocess.Popen(windows_select_command(p),
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
