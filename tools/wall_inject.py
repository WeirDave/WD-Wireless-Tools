"""Put a wall-type template into an .esx, server-side.

Quick Walls has done this since the beginning, but in the browser with JSZip.
That is fine when the browser is the whole workflow; it is not fine for a
preparation pass that also trims the canvas and injects a requirement area,
because both of those are Python. Doing walls in the browser would mean the
file bouncing to the server and back mid-pass, which is the same set of round
trips he asked to be rid of, in a nicer wrapper.

**Adding, not swapping.** Quick Walls remaps drawn segments from one type to
another. This does not touch ``wallSegments.json`` at all - it makes the types
available so he can draw with them, which is what preparation means. Nothing
that is already drawn changes.

**A type already in the project wins.** If the project has a "Concrete" and the
template has a "Concrete", the project's is kept and the template's is skipped.
Replacing it would silently change the attenuation of walls already drawn with
it, which is a design change wearing the clothes of a setup step. The skip is
reported rather than done quietly.

Same posture as everything else here that writes to an .esx: ``metersPerUnit``
and every other member are passed through byte-identical, a backup is taken
before the file is replaced, and anything that cannot be verified is refused
rather than guessed at.
"""
from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

MEMBER = "wallTypes.json"


def _prune_backups(target, protect=None):
    """Trim old backups of `target` to the configured count, after the write.

    Never allowed to fail the operation: a project written correctly must not
    report an error because tidying up afterwards did not work.
    """
    try:
        from tools import backups as _b
        from tools import settings as _s
        keep = (_s.load_settings().get("global") or {}).get("backup_keep")
        keep = _b.DEFAULT_KEEP if keep is None else int(keep)
        return _b.prune_for(target, keep=keep, protect=protect)
    except Exception:
        return None


def _key(name) -> str:
    """How two wall types are decided to be the same one.

    By name, folded and stripped. Ids are useless for this - a template carries
    whatever ids it was captured with, and two projects that both have a
    "Concrete" will not agree on one. The name is what he sees in Ekahau and
    what he means when he says the project already has it.
    """
    return " ".join(str(name or "").split()).casefold()


def _read_members(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


def plan_into_members(members: dict, wall_types: list) -> dict:
    """What injecting these types would do, without doing it."""
    if MEMBER not in members:
        return {"error": "This project has no wallTypes.json, so there is "
                         "nothing to add types to."}
    try:
        doc = json.loads(members[MEMBER])
        existing = doc["wallTypes"]
    except (ValueError, KeyError, TypeError) as exc:
        return {"error": f"wallTypes.json could not be read: {exc}"}

    have = {_key(w.get("name")) for w in existing}
    add, skip = [], []
    seen = set()
    for wt in wall_types or []:
        name = wt.get("name")
        k = _key(name)
        if not k:
            skip.append({"name": name or "(unnamed)",
                         "why": "the template entry has no name"})
            continue
        if k in have or k in seen:
            skip.append({"name": name,
                         "why": "the project already has a wall type with this name"})
            continue
        seen.add(k)
        add.append({"name": name})
    return {"ok": True, "add": add, "skip": skip,
            "existing": len(existing), "total": len(existing) + len(add)}


def inject_into_members(members: dict, wall_types: list) -> dict:
    """Add the missing types to ``members`` in place.

    Returns the same report ``plan_into_members`` gives, so a preview and a run
    describe themselves identically - the preview is not a second description
    that can drift from what actually happens.
    """
    plan = plan_into_members(members, wall_types)
    if plan.get("error"):
        return plan

    doc = json.loads(members[MEMBER])
    existing = doc["wallTypes"]
    used_ids = {w.get("id") for w in existing if w.get("id")}
    by_key = {_key(w.get("name")): w for w in (wall_types or [])}

    for entry in plan["add"]:
        source = by_key[_key(entry["name"])]
        wt = json.loads(json.dumps(source))       # never share structure
        # Keep the template's id when it is free. A template captured out of
        # another project carries that project's ids, and two projects can
        # legitimately collide, so a taken id gets a fresh one rather than
        # overwriting whatever already answers to it.
        if not wt.get("id") or wt["id"] in used_ids:
            wt["id"] = str(uuid.uuid4())
        used_ids.add(wt["id"])
        existing.append(wt)

    members[MEMBER] = (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return plan


def plan_injection(esx_path, wall_types: list) -> dict:
    path = Path(esx_path)
    if not path.is_file():
        return {"error": f"No such project: {path}"}
    try:
        members = _read_members(path)
    except (OSError, zipfile.BadZipFile) as exc:
        return {"error": f"Could not read the project: {exc}"}
    return plan_into_members(members, wall_types)


def inject(esx_path, wall_types: list, dest=None, backup: bool = True) -> dict:
    """Write the types into the project.

    ``dest`` writes a copy and leaves the source alone, which is how the
    preparation pass chains steps without a backup per step. Writing in place
    takes one first.
    """
    path = Path(esx_path)
    if not path.is_file():
        return {"error": f"No such project: {path}"}
    try:
        members = _read_members(path)
    except (OSError, zipfile.BadZipFile) as exc:
        return {"error": f"Could not read the project: {exc}"}

    report = inject_into_members(members, wall_types)
    if report.get("error"):
        return report
    if not report["add"]:
        return {**report, "ok": True, "written": False,
                "note": "Every type in the template is already in this project."}

    target = Path(dest) if dest else path
    backup_path = None
    if backup and not dest:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = path.with_name(f"{path.stem}.previous-{stamp}{path.suffix}")
        try:
            shutil.copy2(path, backup_path)
        except OSError as exc:
            return {"error": f"Could not back the project up, so nothing was "
                             f"changed: {exc}"}

    tmp = target.with_suffix(target.suffix + ".wd-inject.tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
            for name, blob in members.items():
                out.writestr(name, blob)
        tmp.replace(target)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        if backup_path:
            backup_path.unlink(missing_ok=True)
        return {"error": f"Write failed, the project was not changed: {exc}"}

    # Written; only now is an older generation expendable.
    if backup_path:
        _prune_backups(target, protect=str(backup_path))

    return {**report, "ok": True, "written": True, "path": str(target),
            "backup": str(backup_path) if backup_path else None}
