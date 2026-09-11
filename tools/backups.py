"""One place that knows what backups the suite has written, and can clear them.

Six places in this suite copy a file before overwriting it, and until now not
one of them ever deleted anything. That is fine for a single deliberate action
and wrong as a standing policy: an `.esx` runs to several megabytes, a sync
touches many projects, and "we keep every generation forever" fills a disk
rather than protecting anything.

So retention is a number he sets, pruning happens automatically, and the total
is visible before he decides whether clearing it is worth doing. "Delete
backups" with no size attached tells nobody anything.

Two naming conventions exist in the wild and both are recognised:

    <stem>.previous-<stamp><ext>   cloud sync, prep pipeline, wall inject,
                                   wall audit
    <stem>.backup-<stamp><ext>     capacity profiles - the odd one out

A cleanup that only globbed `*.previous-*` would silently leave every capacity
backup on disk, which is exactly the sort of near-miss that makes a cleanup
feature untrustworthy. Recognise both rather than renaming one and breaking
whatever a user already has.

The updater's `<install>.previous-v<version>-<stamp>/` directories are counted
and can be cleared on request, but are never pruned automatically: that folder
is the way back from a bad update, and deleting it on a schedule would remove
the one copy that matters at the moment it matters.
"""
from __future__ import annotations

import os
import re
import shutil
from pathlib import Path

# <stem>.previous-20260911-141500.esx  /  <stem>.backup-20260911-141500.esx
_FILE_RE = re.compile(r"^(?P<stem>.+)\.(?:previous|backup)-(?P<stamp>\d{8}-\d{6})$")
# <install>.previous-v2.92.6-20260911-141500
_DIR_RE = re.compile(r"^(?P<stem>.+)\.previous-v(?P<version>[^-]*)-(?P<stamp>\d{8}-\d{6})$")

DEFAULT_KEEP = 3


def _stat(path: Path):
    try:
        st = path.stat()
        return st.st_size, int(st.st_mtime)
    except OSError:
        return 0, 0


def _dir_size(path: Path) -> int:
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path):
        for fn in filenames:
            try:
                total += (Path(dirpath) / fn).stat().st_size
            except OSError:
                pass
    return total


def classify(path: Path):
    """A backup's identity, or None if this is an ordinary file.

    `owner` is the path the backup was taken *of* - that is what retention
    counts against, so five backups of one project do not hide a single
    backup of another.
    """
    if path.is_dir():
        m = _DIR_RE.match(path.name)
        if not m:
            return None
        return {"kind": "install", "owner": str(path.parent / m.group("stem")),
                "stamp": m.group("stamp")}
    m = _FILE_RE.match(path.stem) if path.suffix else _FILE_RE.match(path.name)
    if not m:
        return None
    owner = path.with_name(m.group("stem") + path.suffix)
    return {"kind": "file", "owner": str(owner), "stamp": m.group("stamp")}


def scan(roots, include_install=True):
    """Every backup under `roots`, newest first, with what it costs.

    Returns {"items": [...], "bytes": int, "count": int}. Each item carries
    path, owner, stamp, bytes and kind, so the caller can group by owner or
    show the biggest offenders without walking the disk again.
    """
    seen, items = set(), []
    for root in roots:
        if not root:
            continue
        root = Path(root)
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root):
            here = Path(dirpath)
            # An install backup is a directory; do not also walk into it and
            # count every file inside as a separate find.
            for name in list(dirnames):
                cand = here / name
                info = classify(cand)
                if info and info["kind"] == "install":
                    dirnames.remove(name)
                    if not include_install or str(cand) in seen:
                        continue
                    seen.add(str(cand))
                    _, mtime = _stat(cand)
                    items.append({"path": str(cand), "owner": info["owner"],
                                  "stamp": info["stamp"], "kind": "install",
                                  "bytes": _dir_size(cand), "mtime": mtime})
            for name in filenames:
                cand = here / name
                info = classify(cand)
                if not info or str(cand) in seen:
                    continue
                seen.add(str(cand))
                size, mtime = _stat(cand)
                items.append({"path": str(cand), "owner": info["owner"],
                              "stamp": info["stamp"], "kind": "file",
                              "bytes": size, "mtime": mtime})
    items.sort(key=lambda i: i["stamp"], reverse=True)
    return {"items": items, "bytes": sum(i["bytes"] for i in items),
            "count": len(items)}


def prune_for(target, keep=DEFAULT_KEEP, protect=None):
    """Keep the newest `keep` backups of one file; delete the rest.

    `keep <= 0` means retention is off and every backup of this file goes -
    he asked for that explicitly, and a setting that only ever accumulates is
    not a setting.

    `protect` is the backup just written. It is never deleted, whatever the
    count says: pruning runs *after* a successful write, and removing the
    generation belonging to the operation in progress would defeat the reason
    the copy was taken.
    """
    target = Path(target)
    parent = target.parent
    if not parent.is_dir():
        return {"deleted": [], "freed": 0, "kept": 0}

    protect = str(Path(protect)) if protect else None
    mine = []
    for cand in parent.iterdir():
        if cand.is_dir():
            continue
        info = classify(cand)
        if not info or info["kind"] != "file":
            continue
        if Path(info["owner"]) != target:
            continue
        size, _ = _stat(cand)
        mine.append({"path": str(cand), "stamp": info["stamp"], "bytes": size})

    mine.sort(key=lambda i: i["stamp"], reverse=True)

    # The one just written always survives, and counts towards the quota - so
    # "keep 3" means three generations exist afterwards, not four.
    keepset = {protect} if protect else set()
    limit = max(0, int(keep))
    for item in mine:
        if item["path"] in keepset:
            continue
        if len(keepset) >= limit:
            break                       # newest-first, so the rest are older
        keepset.add(item["path"])

    deleted, freed = [], 0
    for item in mine:
        if item["path"] in keepset:
            continue
        try:
            os.unlink(item["path"])
            deleted.append(item["path"])
            freed += item["bytes"]
        except OSError:
            pass
    return {"deleted": deleted, "freed": freed, "kept": len(keepset)}


def purge(roots, keep=0, include_install=False):
    """Delete backups across `roots`, keeping the newest `keep` of each file.

    keep=0 clears the lot. Install-tree backups are only touched when asked
    for explicitly - they are the way back from a bad update.
    """
    found = scan(roots, include_install=include_install)
    by_owner = {}
    for item in found["items"]:
        if item["kind"] == "install" and not include_install:
            continue
        by_owner.setdefault((item["owner"], item["kind"]), []).append(item)

    deleted, freed = [], 0
    for (_owner, kind), items in by_owner.items():
        items.sort(key=lambda i: i["stamp"], reverse=True)
        for item in items[max(0, int(keep)):]:
            try:
                if kind == "install":
                    shutil.rmtree(item["path"])
                else:
                    os.unlink(item["path"])
                deleted.append(item["path"])
                freed += item["bytes"]
            except OSError:
                pass
    return {"deleted": deleted, "freed": freed, "count": len(deleted)}


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
