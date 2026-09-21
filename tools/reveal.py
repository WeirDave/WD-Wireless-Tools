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
* **One caller does take a path from the browser**, and this note used to say
  otherwise. Three of the four - the log folder, Quick Walls, Prep - pass a
  path the server already knows. `CloudManager.reveal_in_explorer` passes the
  one the page sent, so the claim "nothing here takes a path from the browser"
  was false, and it was the stated reason this was safe.

  It is safe, for reasons worth writing down properly, because a future reader
  who believes the old sentence might relax the checks that are actually doing
  the work:

  - `Popen` is called **without `shell=True`**, so on Windows the string goes
    to `CreateProcess` verbatim. `&`, `|` and `;` in a path are not operators
    and there is no shell injection here at all.
  - What a string *could* allow is argument injection: a `"` in the path would
    close the quoted argument and let a second one through, and `explorer`
    opens what it is given - including an executable. That needs a `"` in a
    filename, and **Windows does not permit one**. This branch is Windows-only,
    so the character that would be needed cannot exist in a path that reaches
    it.
  - The path must also survive `_assert_inside` against the configured folder
    and must already exist on disk.

  The first two are the load-bearing ones. `_assert_inside` says of itself that
  it is "a sanity check on a path this app's own page supplied, not a boundary
  against an attacker", so it should not be read as the guard here.
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

    **Raises on a quote rather than quoting it.** The module docstring works
    through why argument injection here is not reachable - no `shell=True`,
    and Windows does not permit `"` in a filename - and that reasoning is
    correct and rests on a filesystem rule rather than on anything this code
    does. One caller passes a path the browser sent, this function is
    reachable on any platform through the tests, and the check is one line.
    A guard that costs nothing should not be left out because the argument
    for omitting it currently holds.
    """
    text = str(path)
    if '"' in text or any(ch in text for ch in "\r\n\0"):
        raise ValueError("path contains a character that cannot be quoted "
                         "onto a command line")
    return 'explorer /select,"%s"' % text


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
