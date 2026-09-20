"""What this machine last synced, so "both sides changed" can be said at all.

Two timestamps cannot tell "they changed it" from "we both changed it". A
cloud copy dated later than the local one means the cloud moved; it says
nothing about whether the local one moved as well, because there is nothing to
compare it against. `syncEverythingPlan` therefore sorts every pair into
`cloud_newer`, `local_newer` or in-sync, and the fourth state - **diverged** -
has no way of arising. It is reported as an ordinary one-way difference and
copied over.

The missing quantity is a third number: what the pair looked like the last
time the two sides were the same. With it, four states fall out of two
comparisons:

    cloud moved?  local moved?   verdict
    no            no             in sync
    yes           no             cloud changed - safe to pull
    no            yes            local changed - safe to push
    yes           yes            DIVERGED - stop

**Nothing here resolves a divergence.** That is the point of recording it: the
tool can finally recognise the case it has been silently overwriting, and the
only correct behaviour is to take it out of the batch and say so. A merge of
two `.esx` files is not something this tool can do, and picking a winner is
exactly the data loss the record exists to prevent.

### One user today, and deliberately not built for one

*"That's true now but it could not be true later, so don't be over-simple."*

So the record is **per installation**, describing what *this* machine last
had, not a global truth about the project. That is the model that keeps
working when a second person appears: each machine knows what it last saw,
and `both_changed` is precisely the shape of "a colleague edited the cloud
copy while I was editing mine". A single shared record would have to be stored
somewhere shared, would need its own conflict rules, and would be wrong the
moment two machines wrote it at once.

### Why it is keyed on the cloud id

Ekahau's project id is the one identifier that survives a rename on either
side, and renaming is the thing that moves the dates in the first place. The
local path is recorded as an attribute rather than part of the key, so a file
renamed on disk invalidates the record instead of silently matching the wrong
pair - **an unknown answer is safe and a confidently wrong one is not.**

A push creates a new cloud project rather than writing in place, so the id
changes; `record()` is called after the operation with whatever ids are
current, which writes the new one. The old entry is left to be pruned.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from tools.user_dir import user_dir

STATE_FILE = user_dir() / "sync_state.json"

#: The same tolerance the staleness comparison uses. Filesystems and APIs
#: disagree about a second or two, and a pair that is genuinely untouched must
#: not read as diverged on rounding.
TOLERANCE_S = 2

#: Verdicts. `UNKNOWN` is what every pair says before it has ever been synced
#: through this machine, and it means "fall back to the timestamps" rather
#: than anything is wrong.
UNKNOWN = "unknown"
IN_SYNC = "in_sync"
CLOUD_CHANGED = "cloud_changed"
LOCAL_CHANGED = "local_changed"
BOTH_CHANGED = "both_changed"


def _norm(path) -> str:
    return str(path or "").replace("\\", "/").rstrip("/").lower()


def load(_path=None) -> dict:
    """Every recorded pair, keyed by cloud id. Never raises."""
    p = Path(_path) if _path else STATE_FILE
    if not p.exists():
        return {}
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f) or {}
    except Exception:
        # A truncated or hand-edited file means "no record", which is the
        # safe answer - it degrades to today's timestamp comparison rather
        # than to a wrong verdict.
        return {}
    pairs = data.get("pairs")
    return pairs if isinstance(pairs, dict) else {}


def save(pairs: dict, _path=None) -> None:
    """Write atomically, so an interrupted write cannot leave a half file.

    The whole value of this file is that it is trustworthy; a torn write that
    made one pair look in-sync would be worse than not having it.
    """
    p = Path(_path) if _path else STATE_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix="sync_state_",
                               suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"version": 1, "pairs": pairs}, f, indent=2)
        os.replace(tmp, p)
    except Exception:
        try:
            Path(tmp).unlink(missing_ok=True)
        except Exception:
            pass
        raise


def record(cloud_id, local_path, cloud_mtime, local_mtime,
           direction="", _path=None) -> None:
    """Note that these two were the same, just now.

    Called after an operation that has made them identical - a download over
    the local file, or a replace of the cloud copy. Anything that leaves them
    different must not call this.
    """
    if not cloud_id or not local_path:
        return
    pairs = load(_path)
    pairs[str(cloud_id)] = {
        "localPath": str(local_path),
        "cloudMtime": int(cloud_mtime or 0),
        "localMtime": int(local_mtime or 0),
        "syncedAt": int(time.time()),
        "direction": direction or "",
    }
    save(pairs, _path)


def forget(cloud_id, _path=None) -> None:
    pairs = load(_path)
    if pairs.pop(str(cloud_id), None) is not None:
        save(pairs, _path)


def prune(live_cloud_ids, _path=None) -> int:
    """Drop records for projects that are no longer in the account.

    Returns how many went. Without this the file grows for the life of the
    install, and a recycled id would read against a record for a project that
    no longer exists.
    """
    pairs = load(_path)
    live = {str(i) for i in (live_cloud_ids or [])}
    dead = [k for k in pairs if k not in live]
    for k in dead:
        pairs.pop(k, None)
    if dead:
        save(pairs, _path)
    return len(dead)


def classify(record_entry, cloud_mtime, local_mtime, local_path):
    """Which of the five states this pair is in, given what was recorded.

    `record_entry` is one value out of `load()`, or None.
    """
    if not record_entry:
        return UNKNOWN
    # A local file renamed or moved since the record was written is not the
    # file that record describes. Refusing to answer is correct; guessing is
    # how the wrong project gets overwritten.
    if _norm(record_entry.get("localPath")) != _norm(local_path):
        return UNKNOWN

    was_cloud = int(record_entry.get("cloudMtime") or 0)
    was_local = int(record_entry.get("localMtime") or 0)
    if not was_cloud or not was_local:
        return UNKNOWN

    now_cloud = int(cloud_mtime or 0)
    now_local = int(local_mtime or 0)
    if not now_cloud or not now_local:
        return UNKNOWN

    # Moving *backwards* counts as moved too: a project restored from an older
    # copy is a change, and treating it as "unchanged" would let it be
    # silently overwritten by the other side.
    cloud_moved = abs(now_cloud - was_cloud) > TOLERANCE_S
    local_moved = abs(now_local - was_local) > TOLERANCE_S

    if cloud_moved and local_moved:
        return BOTH_CHANGED
    if cloud_moved:
        return CLOUD_CHANGED
    if local_moved:
        return LOCAL_CHANGED
    return IN_SYNC


def verdict_for(pairs, cloud_id, local_path, cloud_mtime, local_mtime):
    """`classify` against a loaded map, for callers holding many pairs."""
    return classify((pairs or {}).get(str(cloud_id)),
                    cloud_mtime, local_mtime, local_path)
