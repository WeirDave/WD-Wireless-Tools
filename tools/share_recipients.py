"""People he has shared cloud projects with, so he stops retyping them.

He was typing colleagues' addresses from memory every time he shared a
project, which is both tedious and the easiest possible way to send a survey
to a typo. This keeps the ones that worked and offers them back.

**This file holds real colleagues' email addresses.** That makes it rule zero
material in the strongest sense - it is not a path or a filename, it is other
people's contact details. It lives in the user data directory, it is
gitignored, it is never a fixture, never a screenshot, never bundled into a
release and never uploaded anywhere. Every test in this repo uses invented
addresses at RFC 2606 documentation domains. Nothing from a real list is ever
copied into the repository for any reason at all.

It *is* included in the settings export, because that export exists so a
machine can be rebuilt after a wipe - and losing this list is exactly the kind
of small, annoying loss that export was written for. The export is a file he
makes deliberately and keeps himself.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from tools.user_dir import user_dir

FILE_NAME = "share_recipients.json"
SCHEMA_VERSION = 1

#: Enough to cover everyone he actually works with, bounded so the file cannot
#: grow forever on typos. The cap drops the least recently used.
MAX_REMEMBERED = 60

#: Comma, semicolon, whitespace, newline - and the separators Outlook and the
#: Ekahau web UI put on a clipboard when you copy a recipient list.
_SEPARATORS = re.compile(r"[,;\s]+")

#: Deliberately permissive. The authority on whether an address is deliverable
#: is Ekahau, not us; this only catches the shapes that are certainly wrong, so
#: that a legitimate address we failed to anticipate is never refused.
_LOOKS_LIKE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def store_path() -> Path:
    return user_dir() / FILE_NAME


# ------------------------------------------------------------- parsing ----

def split_addresses(text: str) -> list[str]:
    """Split a pasted list into candidate addresses, order preserved.

    Accepts commas, semicolons, spaces and newlines in any combination,
    because a list copied out of an email client arrives in whichever one that
    client felt like using, and he should not have to know which.

    `Some One <a@example.com>` is reduced to the address: pasting from a mail
    client is a normal thing to do and the display name is not ours to keep.
    """
    if not text:
        return []
    cleaned = re.sub(r"[^<>]*<([^>]+)>", r"\1 ", text)
    out, seen = [], set()
    for chunk in _SEPARATORS.split(cleaned):
        candidate = chunk.strip().strip("<>,;").lower()
        if candidate and candidate not in seen:
            seen.add(candidate)
            out.append(candidate)
    return out


def looks_like_email(value: str) -> bool:
    return bool(_LOOKS_LIKE_EMAIL.match((value or "").strip()))


def classify(text: str) -> dict:
    """Split a field into `valid` and `invalid`, keeping both.

    Both halves are returned on purpose. Rejecting the whole field because one
    entry is malformed throws away four correct addresses to complain about a
    fifth, and then he has to retype all five.
    """
    addresses = split_addresses(text)
    return {
        "valid": [a for a in addresses if looks_like_email(a)],
        "invalid": [a for a in addresses if not looks_like_email(a)],
    }


# --------------------------------------------------------------- store ----

def _now() -> str:
    # Microseconds, not seconds. Sharing with two people in the same second is
    # the normal case rather than an edge one - it is a single click - and at
    # second resolution the two entries tie and the order he sees is whatever
    # the sort happened to do.
    return datetime.now(timezone.utc).isoformat(timespec="microseconds")


def _load() -> dict:
    path = store_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": SCHEMA_VERSION, "recipients": []}
    if not isinstance(data, dict):
        return {"version": SCHEMA_VERSION, "recipients": []}
    entries = data.get("recipients")
    if not isinstance(entries, list):
        entries = []
    clean = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        email = str(entry.get("email") or "").strip().lower()
        if not email:
            continue
        clean.append({
            "email": email,
            "lastUsed": str(entry.get("lastUsed") or ""),
            "count": int(entry.get("count") or 1),
        })
    return {"version": SCHEMA_VERSION, "recipients": clean}


def _save(data: dict) -> None:
    path = store_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def recent(limit: int = MAX_REMEMBERED) -> list[dict]:
    """Most recently shared with, first."""
    entries = _load()["recipients"]
    entries.sort(key=lambda e: (e.get("lastUsed") or "", e.get("count") or 0),
                 reverse=True)
    return entries[:max(0, int(limit))]


def remember(emails) -> list[dict]:
    """Record addresses a share actually succeeded for.

    Only successes. Remembering an address that Ekahau rejected would offer
    the typo back to him next time, which is worse than not remembering at
    all - the whole point is to stop him mistyping it twice.
    """
    if isinstance(emails, str):
        emails = [emails]
    wanted = [e.strip().lower() for e in (emails or [])
              if looks_like_email(e)]
    if not wanted:
        return recent()

    data = _load()
    by_email = {e["email"]: e for e in data["recipients"]}
    stamp = _now()
    for email in wanted:
        entry = by_email.get(email)
        if entry:
            entry["lastUsed"] = stamp
            entry["count"] = int(entry.get("count") or 0) + 1
        else:
            by_email[email] = {"email": email, "lastUsed": stamp, "count": 1}

    entries = sorted(by_email.values(),
                     key=lambda e: (e.get("lastUsed") or "", e.get("count") or 0),
                     reverse=True)[:MAX_REMEMBERED]
    data["recipients"] = entries
    try:
        _save(data)
    except OSError:
        pass          # a convenience feature never blocks the share itself
    return entries


def forget(email: str) -> dict:
    """Drop one address. His list, his call - no confirmation needed."""
    target = (email or "").strip().lower()
    data = _load()
    before = len(data["recipients"])
    data["recipients"] = [e for e in data["recipients"] if e["email"] != target]
    removed = len(data["recipients"]) != before
    if removed:
        try:
            _save(data)
        except OSError:
            return {"ok": False, "error": "Could not update the list."}
    return {"ok": True, "removed": removed, "recipients": data["recipients"]}


def forget_all() -> dict:
    data = {"version": SCHEMA_VERSION, "recipients": []}
    try:
        _save(data)
    except OSError:
        return {"ok": False, "error": "Could not clear the list."}
    return {"ok": True, "recipients": []}
