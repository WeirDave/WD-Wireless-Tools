r"""Is this path inside that folder? One answer, because the obvious one is wrong.

Two places in this suite confined a write to a directory by asking whether the
target's text began with the directory's text::

    if not str(target).startswith(str(root)):
        refuse()

That is wrong in a way that reads as right, and it is wrong the same way in
both: a **sibling whose name begins with the root's name** passes it. With a
root of ``C:\Users\me\.wd_wireless_tools``, a payload entry of
``../.wd_wireless_tools_elsewhere/x`` resolves to
``C:\Users\me\.wd_wireless_tools_elsewhere\x``, which starts with the root
string and is not inside the root.

The two were the release-archive guard in ``tools/updater.py`` and the
settings-import guard in ``tools/settings_backup.py``. Neither was reachable by
anything hostile at the time they were found - the archive comes from a
verified release and the bundle is one the user chose - which is exactly why a
string comparison survived in both: nothing was ever going to fail it by
accident.

**Compare components, not characters.** ``extracted`` and
``extracted-elsewhere`` are different path components however similar they
read, and ``Path.relative_to`` compares components. Both paths are resolved
first, so a symlink, a junction, ``..`` and a short 8.3 name all collapse to
the same answer before anything is compared.

``tools/updater.py`` deliberately carries its own copy of this rule rather than
importing it: that module is written to move to the other apps by copying two
files, and a third import would break the contract stated at the top of it.
``tests/test_one_answer_about_containment.py`` runs both implementations over
the same table and fails if they ever disagree.
"""
from __future__ import annotations

import os
from pathlib import Path


def is_within(path, root) -> bool:
    """Is *path* at or inside *root*?

    Resolves both. Returns ``False`` rather than raising when either path
    cannot be resolved - an unanswerable question about containment is a
    refusal, because the failure direction of a guard is toward writing
    somewhere it should not.
    """
    try:
        resolved_root = Path(root).resolve()
        resolved = Path(path).resolve()
    except (OSError, ValueError, RuntimeError):
        return False
    if resolved == resolved_root:
        return True
    try:
        resolved.relative_to(resolved_root)
        return True
    except ValueError:
        return False


def is_within_unresolved(path, root) -> bool:
    """The same question without touching the filesystem.

    `Path.resolve()` opens the path to follow reparse points, and a
    cloud-synced folder is full of them - `cloud_manager._assert_inside` has
    the long note about a project folder being reported outside itself for
    that reason. Where a caller needs the answer without that, this normalises
    case and separators textually and still compares components.

    Weaker than `is_within`: it cannot see through a link. Use it only
    alongside the resolved question, never instead of it.
    """
    try:
        a = os.path.normcase(os.path.abspath(str(path)))
        b = os.path.normcase(os.path.abspath(str(root)))
    except (OSError, ValueError):
        return False
    return a == b or a.startswith(b.rstrip("\\/") + os.sep)
