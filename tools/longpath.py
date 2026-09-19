"""Windows path length, and the two operations that trip over it.

Extracted from `tools/backups.py` when the backup feature was removed. None of
this was ever about backups - it is about `MAX_PATH`, and it is needed by every
write this suite makes to a project whose name is long, which is most of them:
a survey project is named after its site, and a real one measured **232
characters** as the `.esx`.

Kept as its own module rather than folded into a tool, because the same two
questions come up wherever a project is rewritten and the answers are not
obvious:

* **How do I touch a path Windows would refuse?** `long_path`, and
  `write_path` for the form to write at.
* **How do I say why I could not?** `describe_failure`, which exists because
  `str(OSError)` doubles every backslash in the path it names and puts an
  internal path form on screen.

`write_path` is the one with a rule attached: decide before any I/O happens.
Retrying is not available to a write the way it is to a copy - by the time a
write fails there may be a half-built file at the destination, and a retry
would have to reason about clearing it - so the length decides up front.
"""
from __future__ import annotations

import os


# Windows refuses a path of 260 characters or more unless it is asked in the
# one form that turns the limit off. See `long_path`.
MAX_PATH = 260


def long_path(p):
    r"""The same path, in the form Windows accepts past its 260-character limit.

    **This is not a hypothetical.** A survey project is named after its site,
    and a real one measured 232 characters as the `.esx`. Rewriting it goes
    through `<name>.esx.wd-rename.tmp`, 14 characters longer again, so the
    temp file is the first path in the operation to cross 260 - on a project
    that opened perfectly. It failed with `[WinError 3] The system cannot find
    the path specified`, which reads like a missing folder and is nothing of
    the kind. The file was left untouched, which was the correct refusal and
    also a dead end: every retry failed the same way, so the operation simply
    did not work for the projects with the longest names.

    `\\?\` lifts the limit to about 32,767, but only for a **fully qualified**
    path with backslashes and no `.` or `..` - the prefix turns off the
    normalisation that would otherwise fix those up - so `abspath` runs first.
    A UNC path takes the `\\?\UNC\server\share` form rather than keeping `\\`.

    Why this was never seen here: the limit is off by default, and a machine
    with `LongPathsEnabled=1` in the registry - a developer's, typically -
    copies a 295-character path without complaint. The machine that reported
    it has the default. So the length is what has to be handled; the registry
    setting is not something this can rely on.
    """
    if os.name != "nt":
        return str(p)
    s = os.path.abspath(str(p))
    if s.startswith("\\\\?\\"):
        return s
    if s.startswith("\\\\"):
        return "\\\\?\\UNC\\" + s[2:]
    return "\\\\?\\" + s


def write_path(p):
    r"""The form to create or replace a file at `p` with.

    A copy can try the plain path and retry on failure, because a failed copy
    leaves nothing behind. A *write* cannot: by the time it fails there may be
    a half-built archive at the destination, and retrying would have to reason
    about clearing it. So this decides up front, on the one thing that is known
    before any I/O happens - the length.

    This is the half that v2.136.1 missed while the suite still took backups.
    The backup was fixed and the write was not, so on the longest-named
    projects the copy now succeeded and the rewrite then failed with
    `[Errno 2] No such file or directory` on `<project>.esx.wd-rename.tmp` -
    14 characters longer again than the .esx it sits beside. The file was left
    untouched, correctly, and the feature was still unusable, which is the same
    dead end wearing a different message.
    """
    s = str(p)
    if os.name == "nt" and len(s) >= MAX_PATH:
        return long_path(p)
    return s


def describe_failure(exc, dest):
    r"""Why a file could not be written, in a sentence someone can act on.

    **Never `str(exc)`.** `OSError.__str__` appends its filename through
    `repr`, so every backslash in a Windows path is doubled before it reaches
    the screen - and if the path is the `\\?\` retry form, the prefix's own two
    become four. The first report of this fix read

        [Errno 2] The system cannot find the path specified:
        '\\\\?\\C:\\Users\\...\\Projects\\...'

    which is an internal path form, escaped twice, in a toast. The reason and
    the length are what matter; the path itself runs to hundreds of characters
    and belongs in the log, not in a notification.

    `strerror` is the clean half of the exception - "The system cannot find the
    path specified" with no filename attached - so that is what is quoted.
    """
    reason = (getattr(exc, "strerror", None) or "").strip()
    if not reason:
        #: Some OSErrors carry no strerror. `repr` of the exception still beats
        #: `str`, which is the one that drags the escaped filename along.
        reason = exc.__class__.__name__
    reason = reason.rstrip(".")

    n = len(str(dest))
    if os.name == "nt" and n >= MAX_PATH:
        return (f"{reason}. That path is {n} characters and Windows "
                f"stops at {MAX_PATH} - shorten the project or folder name, "
                f"or move the folder nearer the top of the drive.")
    return f"{reason}."
