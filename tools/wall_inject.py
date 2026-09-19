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
and every other member are passed through byte-identical, the rebuild goes to
a temp file that is renamed over the top, and anything that cannot be verified
is refused rather than guessed at.
"""
from __future__ import annotations

import json
import shutil
import uuid
import zipfile
from pathlib import Path

MEMBER = "wallTypes.json"


def _key(name) -> str:
    """How two wall types are decided to be the same one.

    By name, folded and stripped. Ids are useless for this - a template carries
    whatever ids it was captured with, and two projects that both have a
    "Concrete" will not agree on one. The name is what he sees in Ekahau and
    what he means when he says the project already has it.
    """
    return " ".join(str(name or "").split()).casefold()


def _words(name) -> tuple:
    """The same name with Ekahau's own renaming folded out.

    Ekahau renamed its stock wall types between releases: "Dry Wall" became
    "Wall, Dry", "Thin Door" became "Door, Thin", "Thick Window" became
    "Window, Thick". An exact name match sees those as different types, so a
    project made in an older release collected a second copy of each - one real
    run came out with 43 wall types and ten near-duplicate pairs, which is not
    a project anybody wants to open.

    Same words, in any order, with punctuation dropped: that is the same type
    under a new name. Different words are left alone, so "Wall, Dry" and
    "Wall, Dry, Hollow" stay two types, and none of his own five - Framery Pod,
    the steel and rack walls - collides with anything stock.
    """
    cleaned = "".join(c if (c.isalnum() or c.isspace()) else " " for c in str(name or ""))
    return tuple(sorted(cleaned.casefold().split()))


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
    # Same words in a different order is Ekahau's own renaming, not a new type.
    renamed = {_words(w.get("name")): w.get("name") for w in existing}
    add, skip = [], []
    seen, seen_words = set(), set()
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
        w = _words(name)
        if w in renamed:
            skip.append({"name": name,
                         "why": "the project already has this type under Ekahau's "
                                "older name, “%s”" % renamed[w]})
            continue
        if w in seen_words:
            skip.append({"name": name,
                         "why": "the template names this type twice"})
            continue
        seen.add(k)
        seen_words.add(w)
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

    _resolve_keybind_collisions(existing, plan["add"])

    members[MEMBER] = (json.dumps(doc, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    return plan


def _resolve_keybind_collisions(existing: list, added: list) -> None:
    """One number key, one wall type. The incoming type wins.

    Adding types without touching this leaves two wall types claiming the same
    slot, and in Ekahau a number key can only draw one of them - so a shortcut
    he has used for months silently starts drawing something else, or nothing.

    Found by applying his template to a project holding Ekahau's stock types:
    the project's "Wall, Concrete" carried Ekahau's slot 5, his template put
    "Door, Steel Fire/Exit" on 5, and the result had two types on 5 and nothing
    on 2. Nothing errored, and the file opened.

    Quick Walls has always done this - `mergeTemplateTypes` in `walls.js` drops
    the older binding with the same reasoning written beside it. Injection is
    the other way his template reaches a project, through Prep, and it did not.
    Keeping the two in step matters more than which rule wins: a shortcut that
    depends on which tool applied the template is not a shortcut.

    Only bindings the *incoming* types claim are resolved. A collision already
    sitting in the project is his and is left alone - this adds types, it does
    not tidy up after Ekahau.
    """
    incoming = {id(w) for w in existing[len(existing) - len(added):]} if added else set()
    claimed = {}
    for wt in existing:
        if id(wt) in incoming:
            num = wt.get("keybindNumber")
            if isinstance(num, int) and 1 <= num <= 9:
                claimed[num] = id(wt)
    for wt in existing:
        num = wt.get("keybindNumber")
        if num in claimed and id(wt) != claimed[num]:
            wt.pop("keybindNumber", None)


def plan_injection(esx_path, wall_types: list) -> dict:
    path = Path(esx_path)
    if not path.is_file():
        return {"error": f"No such project: {path}"}
    try:
        members = _read_members(path)
    except (OSError, zipfile.BadZipFile) as exc:
        return {"error": f"Could not read the project: {exc}"}
    return plan_into_members(members, wall_types)


def inject(esx_path, wall_types: list, dest=None) -> dict:
    """Write the types into the project.

    ``dest`` writes a copy and leaves the source alone, which is how the
    preparation pass chains steps. With no ``dest`` the project is rewritten
    in place, through a temp file that is renamed over the top - so the `.esx`
    is either entirely the old one or entirely the new one.

    **Nothing is copied aside first.** Quick Walls, the only thing a person
    drives this from, hands the result back as a browser download under a new
    name and never touches the original at all.
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

    tmp = target.with_suffix(target.suffix + ".wd-inject.tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
            for name, blob in members.items():
                out.writestr(name, blob)
        tmp.replace(target)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        return {"error": f"Write failed, the project was not changed: {exc}"}

    return {**report, "ok": True, "written": True, "path": str(target)}
