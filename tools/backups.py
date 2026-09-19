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

#: The folder Cloud Manager files a replaced project under, inside the project
#: folder. It is the canonical copy of the name: `cloud_manager.BACKUP_DIR_NAME`
#: is the same string and `tests/test_backup_folder.py` asserts they agree,
#: because this module has to be able to walk that mapping *backwards* - a
#: backup living in `backups/<site>/` came from `<site>/`, and a restore that
#: guessed at that would put the file somewhere nobody is looking.
BACKUP_DIR_NAME = "backups"


# Windows refuses a path of 260 characters or more unless it is asked in the
# one form that turns the limit off. See `long_path`.
MAX_PATH = 260


def long_path(p):
    r"""The same path, in the form Windows accepts past its 260-character limit.

    **This is not a hypothetical.** A backup is `<stem>.previous-<stamp><ext>`,
    which adds 25 characters to a name that is already the longest thing in the
    tree, and a survey project is named after its site. A real one measured 232
    characters as the `.esx` and **265** as the backup. Opening the project
    worked, creating `backups/<site>/` worked - only the copy failed, with
    `[WinError 3] The system cannot find the path specified`, which reads like
    a missing folder and is nothing of the kind. Nothing was written, which was
    the correct refusal and also a dead end: every retry failed the same way,
    so the feature simply did not work for the projects with the longest names.

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


def _try_both(op, *paths):
    """Run `op` on the paths as given; on failure, run it on their long forms.

    Plain first, deliberately. The prefixed form is accepted everywhere that
    matters, but it is not identical - it bypasses normalisation, and some
    network redirectors dislike it - so the ordinary case keeps the ordinary
    path and only a path that has actually failed takes the other route.
    """
    try:
        return op(*paths)
    except OSError:
        if os.name != "nt":
            raise
        try:
            return op(*[long_path(p) for p in paths])
        except OSError as exc:
            #: The retry's exception names the prefixed path, and `OSError`
            #: puts its filename through `repr`. Between them that turns
            #: C:\Users\… into '\\\\?\\C:\\Users\\…' in anything that prints
            #: the error - four backslashes where the path has one, which is
            #: what "a lot of extra backslashes" looked like on screen.
            #: Re-point it at the path the caller actually asked for.
            exc.filename = str(paths[-1])
            exc.filename2 = None
            raise


def copy_for_backup(src, dest):
    r"""Copy `src` to `dest` for safekeeping, working past MAX_PATH.

    Returns `dest` **as it was given**, not the prefixed form: the caller shows
    that path to the person whose file it is and hands it to `prune_for`, and
    `\\?\C:\...` is not a path to tell anyone to go and look for.

    The name is never shortened to make it fit. `classify` reads the owner back
    out of the filename, so a trimmed stem would name a file that does not
    exist, `prune_for` would never match it again, and the backup would be
    correct, invisible to retention, and kept for ever.
    """
    _try_both(shutil.copy2, str(src), str(dest))
    return dest


def write_path(p):
    r"""The form to create or replace a file at `p` with.

    `copy_for_backup` can try the plain path and retry, because a failed copy
    leaves nothing behind. A *write* cannot: by the time it fails there may be
    a half-built archive at the destination, and retrying would have to reason
    about clearing it. So this decides up front, on the one thing that is known
    before any I/O happens - the length.

    This is the half that v2.136.1 missed. The backup was fixed and the write
    was not, so on the longest-named projects the backup now succeeded and the
    rewrite then failed with `[Errno 2] No such file or directory` on
    `<project>.esx.wd-rename.tmp` - 14 characters longer again than the .esx it
    sits beside. The file was left untouched, correctly, and the feature was
    still unusable, which is the same dead end wearing a different message.
    """
    s = str(p)
    if os.name == "nt" and len(s) >= MAX_PATH:
        return long_path(p)
    return s


def describe_failure(exc, dest):
    r"""Why a backup could not be written, in a sentence someone can act on.

    **Never `str(exc)`.** `OSError.__str__` appends its filename through
    `repr`, so every backslash in a Windows path is doubled before it reaches
    the screen - and if the path is the `\\?\` retry form, the prefix's own two
    become four. The first report of this fix read

        [Errno 2] The system cannot find the path specified:
        '\\\\?\\C:\\Users\\...\\backups\\...'

    which is an internal path form, escaped twice, in a toast. The reason and
    the length are what matter; the path itself is 265 characters and belongs
    in the log, not in a notification.

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
        return (f"{reason}. The backup path is {n} characters and Windows "
                f"stops at {MAX_PATH} - shorten the project or folder name, "
                f"or move the folder nearer the top of the drive.")
    return f"{reason}."


def _stat(path: Path):
    try:
        st = path.stat()
        return st.st_size, int(st.st_mtime)
    except OSError:
        pass
    #: A backup long enough to need the prefix still has to be counted and
    #: still has to be prunable - otherwise retention silently stops applying
    #: to exactly the projects that generate the biggest files.
    try:
        st = os.stat(long_path(path))
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


def prune_for(target, keep=DEFAULT_KEEP, protect=None, extra_dirs=()):
    """Keep the newest `keep` backups of one file; delete the rest.

    `keep <= 0` means retention is off and every backup of this file goes -
    he asked for that explicitly, and a setting that only ever accumulates is
    not a setting.

    `protect` is the backup just written. It is never deleted, whatever the
    count says: pruning runs *after* a successful write, and removing the
    generation belonging to the operation in progress would defeat the reason
    the copy was taken.

    `extra_dirs` are the other folders a backup of `target` can be filed in.
    **This parameter is the fix for a setting that had quietly stopped
    working.** Cloud Manager stopped writing a sibling `.previous-` copy and
    started filing it under `<project folder>/backups/<site>/`, which is what
    he asked for - but pruning still only looked in `target.parent`, where
    there is now nothing to find. So "keep 3" kept every generation ever
    taken, of every project replaced by a sync, for as long as the folder had
    existed, and the number in Settings did nothing at all. Measured on a
    fixture: four copies written with keep=2 left four copies on disk.

    A backup in one of those folders names its owner as the same filename
    *inside that folder*, so the comparison is on the name rather than on the
    whole path. Pass only the folder that holds this file's backups - the
    per-site sub-folder, never the `backups/` root - or a project of the same
    name from another site would be pruned against this one's quota.
    """
    target = Path(target)
    folders, seen_dirs = [], set()
    for folder in [target.parent] + [Path(d) for d in (extra_dirs or ()) if d]:
        key = os.path.normcase(os.path.abspath(str(folder)))
        if key in seen_dirs:
            continue
        seen_dirs.add(key)
        folders.append(folder)

    protect = str(Path(protect)) if protect else None
    mine, seen = [], set()
    for parent in folders:
        if not parent.is_dir():
            continue
        for cand in parent.iterdir():
            if cand.is_dir():
                continue
            info = classify(cand)
            if not info or info["kind"] != "file":
                continue
            if Path(info["owner"]).name != target.name:
                continue
            key = os.path.normcase(os.path.abspath(str(cand)))
            if key in seen:
                continue
            seen.add(key)
            size, _ = _stat(cand)
            mine.append({"path": str(cand), "stamp": info["stamp"], "bytes": size})

    if not mine:
        return {"deleted": [], "freed": 0, "kept": 0}

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
            _try_both(os.unlink, item["path"])
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
                    _try_both(shutil.rmtree, item["path"])
                else:
                    _try_both(os.unlink, item["path"])
                deleted.append(item["path"])
                freed += item["bytes"]
            except OSError:
                pass
    return {"deleted": deleted, "freed": freed, "count": len(deleted)}



# ── The window onto all of it ────────────────────────────────────────────────
#
# Everything above this line writes backups, counts them and throws them away.
# What was missing was the other half: a way to *look* at what has been kept
# and put one back. "I know we have no window to it right now" - and the six
# places that copy a file aside were all reporting a path into a folder he had
# no way to open from inside the tool.
#
# So: `browse` lists, `restore` puts one back, `remove` deletes named ones.
# All three take the same `roots` the rest of the module takes, and all three
# refuse a path outside them - the browser hands these in, and a page that can
# name any path on the disk is a page that can restore over any file on it.


def _key(p):
    """A path in the form two paths can be compared in, on either OS."""
    return os.path.normcase(os.path.abspath(str(p)))


def _under(child, parent):
    """Is `child` inside `parent`? Case-folded, and never fooled by `..`."""
    c, p = _key(child), _key(parent)
    return c == p or c.startswith(p.rstrip(os.sep) + os.sep)


def inside_roots(path, roots):
    """The first root `path` sits under, or None.

    The check is on the normalised absolute path rather than on the resolved
    one: `resolve()` follows symlinks, and a project folder reached through a
    junction - which is how Dropbox and OneDrive folders are often mounted -
    would resolve somewhere outside the root it was legitimately reached by,
    and be refused.
    """
    for root in roots or ():
        if root and _under(path, root):
            return str(root)
    return None


def restore_target(path, roots):
    """Where this backup came from, or None if it is not a backup at all.

    Two shapes, and the difference is the whole reason this function exists:

    * a sibling copy - `<site>/Survey.previous-<stamp>.esx` - came from
      `<site>/Survey.esx`, which is what `classify` already reports as the
      owner;
    * a filed copy - `<project folder>/backups/<site>/Survey.previous-<stamp>.esx`
      - came from `<project folder>/<site>/Survey.esx`, which is **not** where
      `classify` points. Its owner is a path inside the backups folder that has
      never existed, because that value exists to group generations for
      retention rather than to name a live file.

    Restoring to `classify`'s owner would therefore write the recovered project
    into the backups folder - a folder Cloud Manager deliberately does not
    read - and report success. The file would be safe, invisible, and not where
    he went to look for it.
    """
    path = Path(path)
    info = classify(path)
    if not info:
        return None
    owner = Path(info["owner"])
    for root in roots or ():
        if not root:
            continue
        holder = Path(root) / BACKUP_DIR_NAME
        if _under(owner, holder):
            try:
                rel = Path(os.path.relpath(str(owner), str(holder)))
            except ValueError:          # different drives on Windows
                continue
            return Path(root) / rel
    return owner


def browse(roots, include_install=True):
    """Every backup under `roots`, grouped by the file it was taken of.

    One group per original file, newest generation first, because that is the
    question being asked of it: not "what is in this folder" but "what do I
    have of *this project*, and how far back does it go".

    Each item carries where a restore would put it and whether that file is
    still there, so the page can say "replaces the copy you have" or "puts a
    file back that is gone" without asking the disk a second time.
    """
    found = scan(roots, include_install=include_install)
    groups = {}
    for item in found["items"]:
        target = restore_target(item["path"], roots) if item["kind"] == "file" else Path(item["owner"])
        gkey = _key(target)
        g = groups.get(gkey)
        if not g:
            g = groups[gkey] = {
                "key": gkey,
                "target": str(target),
                "name": target.name,
                "folder": str(target.parent),
                "exists": target.exists(),
                "kind": item["kind"],
                "items": [], "bytes": 0, "count": 0,
            }
        g["items"].append({
            "path": item["path"],
            "name": Path(item["path"]).name,
            "folder": str(Path(item["path"]).parent),
            "stamp": item["stamp"],
            "when": item["mtime"],
            "bytes": item["bytes"],
            "kind": item["kind"],
            "restoreTo": str(target),
            "targetExists": g["exists"],
        })
        g["bytes"] += item["bytes"]
        g["count"] += 1
        # A group holding both an install backup and a file backup cannot
        # happen - they key off different paths - but if it ever did, the
        # install kind is the one that must win, because it is the one that
        # must not be offered a restore button.
        if item["kind"] == "install":
            g["kind"] = "install"

    out = list(groups.values())
    for g in out:
        g["items"].sort(key=lambda i: i["stamp"], reverse=True)
        g["newest"] = g["items"][0]["stamp"] if g["items"] else ""
        g["newestWhen"] = g["items"][0]["when"] if g["items"] else 0
    out.sort(key=lambda g: (g["newest"], g["name"]), reverse=True)
    return {"groups": out, "bytes": found["bytes"], "count": found["count"],
            "roots": [str(r) for r in roots if r]}


def restore(path, roots, stamp=None):
    """Put `path` back where it came from, keeping what is there now.

    The copy being replaced is backed up first, with the same naming and into
    the same folder the backup being restored sits in. That is not ceremony:
    restoring is itself a destructive write, and a restore of the wrong
    generation with no way back would be a worse version of the problem
    backups exist for. The backup being restored is **left on disk** - putting
    a copy back is not the same as spending it, and a file manager whose
    restore quietly consumed the file would be the last thing anyone expects.

    Refusals, in the order they are checked: a path outside `roots`, a path
    that is not a backup at all, an install-tree backup (rolling an install
    back is the updater's job and needs its own confirm), and a backup that
    has gone since the page drew it.
    """
    path = Path(path)
    if not inside_roots(path, roots):
        return {"error": "That file is not in a folder this tool looks after."}
    info = classify(path)
    if not info:
        return {"error": "That is not a backup copy, so there is nothing to "
                         "put back."}
    if info["kind"] == "install":
        return {"error": "That is a previous copy of the app itself. Rolling "
                         "an install back is done from About - this only "
                         "restores files."}
    if not path.is_file():
        return {"error": "That backup is no longer on disk. Refresh the list."}

    target = restore_target(path, roots)
    if target is None:
        return {"error": "Could not work out where that backup came from."}

    from datetime import datetime as _dt
    stamp = stamp or _dt.now().strftime("%Y%m%d-%H%M%S")

    kept = None
    if target.exists():
        kept = path.with_name(f"{target.stem}.previous-{stamp}{target.suffix}")
        try:
            copy_for_backup(target, kept)
        except OSError as exc:
            return {"error": "The copy that is there now could not be saved, "
                             "so nothing was replaced. "
                             + describe_failure(exc, kept)}
    else:
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            return {"error": "The folder it came from is gone and could not "
                             "be recreated. " + describe_failure(exc, target)}

    # Copy aside, then rename over the top. `os.replace` is atomic, so the
    # live file is either the old one or the new one and never half of a copy
    # that ran out of disk half way through a 200 MB project.
    tmp = target.with_suffix(target.suffix + ".wd-restore.tmp")
    try:
        copy_for_backup(path, tmp)
        _try_both(os.replace, write_path(tmp), write_path(target))
    except OSError as exc:
        try:
            _try_both(os.unlink, write_path(tmp))
        except OSError:
            pass
        return {"error": "The restore could not be written, and the file that "
                         "was there is untouched. " + describe_failure(exc, target)}

    size, _ = _stat(target)
    return {"ok": True, "restored": str(target), "from": str(path),
            "kept": str(kept) if kept else None, "replaced": bool(kept),
            "bytes": size}


def remove(paths, roots):
    """Delete the named backups, re-deciding at delete time what may go.

    The page sends paths; this does not trust them. Every one is looked up in
    a fresh scan of `roots`, and anything that is not in it - outside the
    roots, not a backup, already gone, or arrived since - is skipped with a
    reason rather than deleted. Same rule as the realign action and the
    housekeeping sweep: the server re-derives its own work, so a stale page
    cannot delete something that has changed under it.
    """
    wanted = {}
    for p in paths or ():
        if p:
            wanted.setdefault(_key(p), str(p))
    if not wanted:
        return {"ok": True, "deleted": [], "freed": 0, "count": 0, "skipped": []}

    known = {_key(i["path"]): i for i in scan(roots, include_install=True)["items"]}

    deleted, freed, skipped = [], 0, []
    for key, shown in wanted.items():
        item = known.get(key)
        if not item:
            skipped.append({"path": shown,
                            "reason": "no longer a backup this tool keeps"})
            continue
        try:
            if item["kind"] == "install":
                _try_both(shutil.rmtree, item["path"])
            else:
                _try_both(os.unlink, item["path"])
        except OSError as exc:
            skipped.append({"path": item["path"],
                            "reason": describe_failure(exc, item["path"])})
            continue
        deleted.append(item["path"])
        freed += item["bytes"]
    return {"ok": True, "deleted": deleted, "freed": freed,
            "count": len(deleted), "skipped": skipped}


def human_size(n):
    n = float(n or 0)
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"
