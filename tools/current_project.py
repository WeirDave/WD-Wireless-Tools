"""The project the person is working on, and the ones they worked on before.

Every tool used to ask for the `.esx` on its own: Quick Walls and Prep each
kept a private "opened from disk" path, Report kept a third, and the drop-box
tools kept none, so a project that went through Prep, Quick Walls, AP Labeler
and Report was picked or dropped four times. This is the one place that
remembers which project is current, so the header of every tool can say so and
offer to open it there.

**What is stored, and where.** `current_project.json` in the user folder
(never the install tree, so an update cannot touch it): the current path and up
to ``MAX_RECENT`` recent ones, newest first. They are real file paths, which
makes this rule-zero material - gitignored by living outside the repository,
absent from the release, never a fixture. Tests invent their paths.

**Only paths the person chose.** A path gets in by the native file picker, by
being a project a tool wrote next to the one they chose, or by being picked
from this list. ``is_known`` is how the server decides whether a request that
names a path may read it, so a request cannot turn the project routes into a
way to read an arbitrary file: the same stance as ``_PICKED_ESX``.

**A path is not a promise.** The file can be moved or deleted between sessions,
so every entry carries ``exists`` and nothing reads one without checking again
at the moment of use.

**A dropped file is not remembered.** A browser hands over the bytes and a
name, never a path, so a project dragged into a tool cannot become current. The
header says to choose it with the picker instead.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from tools import atomic_write
from tools.user_dir import user_dir

STORE_NAME = "current_project.json"
MAX_RECENT = 12

_LOCK = threading.RLock()


def store_path() -> Path:
    return user_dir() / STORE_NAME


def _key(path) -> str:
    """The identity of a path: what Windows treats as one file."""
    return os.path.normcase(os.path.abspath(str(path)))


def _load() -> dict:
    try:
        doc = json.loads(store_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        doc = {}
    if not isinstance(doc, dict):
        doc = {}
    recent = []
    seen = set()
    for item in doc.get("recent") or []:
        p = item.get("path") if isinstance(item, dict) else None
        if isinstance(p, str) and p and _key(p) not in seen:
            seen.add(_key(p))
            recent.append({"path": p, "opened": str(item.get("opened") or "")})
    cur = doc.get("current")
    return {"current": cur if isinstance(cur, str) and cur else None,
            "recent": recent[:MAX_RECENT]}


def _save(doc: dict) -> None:
    atomic_write.write_json(store_path(), {"version": 1, **doc})


def describe(path) -> dict:
    """What the header and the recent list show about a path."""
    p = Path(path)
    out = {"path": str(p), "name": p.name, "dir": str(p.parent),
           "exists": False, "bytes": None, "modified": None}
    try:
        st = p.stat()
    except OSError:
        return out
    if p.is_file():
        out.update(exists=True, bytes=st.st_size,
                   modified=datetime.fromtimestamp(
                       st.st_mtime, timezone.utc).isoformat())
    return out


def _acceptable(path):
    """The path as a Path if it is an .esx file that exists, else None."""
    try:
        p = Path(str(path))
    except (TypeError, ValueError):
        return None
    if p.suffix.lower() != ".esx" or not p.is_file():
        return None
    return p


@atomic_write.serialised(_LOCK)
def set_current(path) -> dict:
    """Make `path` the current project and put it at the top of the recent list."""
    p = _acceptable(path)
    if p is None:
        return {"ok": False, "error": "That is not an .esx project file that "
                                      "exists."}
    doc = _load()
    now = datetime.now(timezone.utc).isoformat()
    doc["recent"] = ([{"path": str(p), "opened": now}]
                     + [r for r in doc["recent"] if _key(r["path"]) != _key(p)]
                     )[:MAX_RECENT]
    doc["current"] = str(p)
    _save(doc)
    return {"ok": True, "project": describe(p)}


def current():
    """The current project as `describe` shows it, or None."""
    cur = _load()["current"]
    return describe(cur) if cur else None


def recent() -> list:
    return [dict(describe(r["path"]), opened=r["opened"])
            for r in _load()["recent"]]


def is_known(path) -> bool:
    """Was this path chosen by the person - current, or on the recent list?"""
    if not isinstance(path, str) or not path:
        return False
    doc = _load()
    known = {_key(r["path"]) for r in doc["recent"]}
    if doc["current"]:
        known.add(_key(doc["current"]))
    return _key(path) in known


def current_path():
    """The current project's path if it is still a readable .esx, else None.

    What every server-side read goes through, so a file that was moved or
    replaced by something that is not a project is refused at the moment of use.
    """
    cur = _load()["current"]
    return _acceptable(cur) if cur else None


@atomic_write.serialised(_LOCK)
def use(path) -> dict:
    """Make a project from the recent list current again."""
    if not is_known(path):
        return {"ok": False, "error": "That project is not on the list. Choose "
                                      "it again."}
    result = set_current(path)
    if not result["ok"]:
        result["error"] = ("That project is not where it was. It may have been "
                           "moved or deleted.")
    return result


@atomic_write.serialised(_LOCK)
def forget(path=None) -> dict:
    """Stop treating `path` as current and drop it from the list. With no path,
    only stop treating the current one as current: it stays on the list."""
    doc = _load()
    if path is None:
        doc["current"] = None
    else:
        doc["recent"] = [r for r in doc["recent"] if _key(r["path"]) != _key(path)]
        if doc["current"] and _key(doc["current"]) == _key(path):
            doc["current"] = None
    _save(doc)
    return {"ok": True}


@atomic_write.serialised(_LOCK)
def clear() -> dict:
    """Forget everything: the current project and the whole recent list."""
    _save({"current": None, "recent": []})
    return {"ok": True}
