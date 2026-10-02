"""
WD — Capacity profile templates.

A capacity template says what a person brings onto the network: how many
devices, of which kinds, doing what. Ekahau expresses that as a requirement
attached to an area, carrying a list of capacity items - a device count, a
device profile and a usage profile each.

The template is *captured from an .esx*, not hand-authored. Set a project up in
Ekahau the way you want it, point this at the file, and it reads the profiles
and ratios back out. Ekahau stays the editor; nobody has to learn a JSON format
to describe a laptop.

What is stored is **ratios, not counts**. A project built for 500 people that
carries 1500 devices stores "3 devices per occupant, split like so", which then
applies correctly to a 200-person building. Headcount is the only number the
user supplies at apply time; every proportion lives in the template data. That
matters because the next person to use this will have a different device mix,
and none of it should be hiding in code.
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import zipfile
from pathlib import Path
from tools.user_dir import user_dir

USER_DIR = user_dir() / "capacity"
HERE = Path(__file__).resolve().parent
BUILTIN_DIR = HERE.parent / "templates"
TPL_SUFFIX = "_capacitytemplate.json"

# Ekahau has moved these between files across versions, so nothing here keys
# off a filename. These are only the places worth looking first; the resolver
# below falls back to scanning every member.
LIKELY_PROFILE_FILES = (
    "deviceProfiles.json",
    "usageProfiles.json",
    "requirements.json",
    "applicationProfiles.json",
)


def _read_members(zf: zipfile.ZipFile) -> dict:
    """Every JSON member of the archive, parsed, keyed by name."""
    out = {}
    for info in zf.infolist():
        if not info.filename.endswith(".json"):
            continue
        try:
            out[info.filename] = json.loads(zf.read(info.filename).decode("utf-8"))
        except Exception:
            continue
    return out


def _index_by_id(members: dict) -> dict:
    """Map every object id in the project to the object itself.

    Profiles are referenced by id from areas.json, and which file holds them
    has changed between Ekahau releases. Indexing the whole project means the
    reference resolves wherever it actually lives, including files this code
    has never heard of.
    """
    index = {}
    ordered = sorted(members, key=lambda n: (n not in LIKELY_PROFILE_FILES, n))
    for name in ordered:
        body = members[name]
        if not isinstance(body, dict):
            continue
        for key, val in body.items():
            if not isinstance(val, list):
                continue
            for obj in val:
                if isinstance(obj, dict) and isinstance(obj.get("id"), str):
                    index.setdefault(obj["id"], {"member": name, "collection": key, "obj": obj})
    return index


def _label_for(entry) -> str:
    """A human name for a profile object, whatever the field is called."""
    if not entry:
        return ""
    obj = entry["obj"]
    for field in ("name", "title", "label", "displayName"):
        val = obj.get(field)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _live_floor_ids(members: dict) -> set:
    fp = members.get("floorPlans.json") or {}
    return {f.get("id") for f in fp.get("floorPlans", []) if isinstance(f, dict) and f.get("id")}


def extract(esx_path) -> dict:
    """Read device/usage profiles and capacity ratios out of a project.

    Returns a report describing what was found, including the raw counts, so
    the caller can show its work before anything is saved. Ratios are computed
    only once an occupant count is supplied - see `derive_template`.
    """
    esx_path = Path(esx_path)
    with zipfile.ZipFile(esx_path) as zf:
        members = _read_members(zf)

    areas = (members.get("areas.json") or {}).get("areas", [])
    index = _index_by_id(members)
    live = _live_floor_ids(members)

    # Capacity items belong to an area, and rows are kept exactly as authored.
    # Merging two rows that share a device and usage profile would look tidier
    # and lose the point: a work phone and a personal phone are the same
    # hardware on the same usage tier in different proportions, and collapsing
    # them throws away the split the designer sat down and decided. The panel
    # this is read back from shows six rows; so does this.
    candidates = []
    orphan_areas = 0

    for area in areas:
        if not isinstance(area, dict):
            continue
        items = area.get("capacityItems")
        if not isinstance(items, list) or not items:
            continue
        # An area whose floor plan is gone is left over from a deleted floor.
        # Its numbers are real but it describes nothing, so it is reported and
        # not counted.
        if area.get("floorPlanId") and area["floorPlanId"] not in live:
            orphan_areas += 1
            continue
        rows = []
        for item in items:
            if not isinstance(item, dict):
                continue
            count = item.get("deviceCount")
            if not isinstance(count, (int, float)) or count <= 0:
                continue
            dev_id = item.get("deviceProfileId") or ""
            use_id = item.get("usageProfileId") or ""
            rows.append({
                "deviceProfileId": dev_id,
                "usageProfileId": use_id,
                "device": _label_for(index.get(dev_id)) or "(unnamed device profile)",
                "usage": _label_for(index.get(use_id)) or "(unnamed usage profile)",
                "deviceCount": count,
            })
        if rows:
            candidates.append({"area": area, "rows": rows,
                               "total": sum(r["deviceCount"] for r in rows)})

    areas_seen = len(candidates)
    # One area per floor plan is what gets written, so one area is what gets
    # captured. Where several carry capacity the largest is the representative
    # one and the rest are reported, rather than being summed into a mixture
    # that describes no space that actually exists.
    chosen = max(candidates, key=lambda c: c["total"]) if candidates else None
    rows = chosen["rows"] if chosen else []
    requirement_ids = [chosen["area"].get("requirementId")] if chosen and chosen["area"].get("requirementId") else []
    others_differ = any(
        c is not chosen and [(r["device"], r["usage"], r["deviceCount"]) for r in c["rows"]]
        != [(r["device"], r["usage"], r["deviceCount"]) for r in rows]
        for c in candidates
    )

    total = sum(r["deviceCount"] for r in rows)

    req_entry = index.get(requirement_ids[0]) if requirement_ids else None

    return {
        "ok": True,
        "source": esx_path.name,
        "rows": rows,
        "totalDevices": total,
        "areasWithCapacity": areas_seen,
        "otherAreasDiffer": others_differ,
        "orphanAreasSkipped": orphan_areas,
        "requirementName": _label_for(req_entry),
        "deviceProfileCount": len({r["deviceProfileId"] for r in rows}),
        "usageProfileCount": len({r["usageProfileId"] for r in rows}),
        "profileDefs": _capture_profile_defs(
            index, rows, requirement_ids[0] if requirement_ids else None),
        # Every device and usage profile the project has, with what each one
        # depends on, so a template can be built from Ekahau's own profiles
        # rather than only captured from areas someone already filled in.
        "available": _available_profiles(index),
    }


def _available_profiles(index: dict) -> dict:
    """Every device and usage profile in the project, by name.

    `devices` and `usages` are the names, sorted, for the editor's pickers;
    `defs` holds each one's object and dependencies, so a template built from
    them carries them to a project that lacks them."""
    out = {"devices": {}, "usages": {}}
    for obj_id, entry in index.items():
        bucket = {"deviceProfiles": "devices",
                  "usageProfiles": "usages"}.get(entry.get("collection"))
        if not bucket:
            continue
        label = _label_for(entry)
        if not label or label in out[bucket]:
            continue
        out[bucket][label] = _with_deps(index, obj_id)
    return {
        "devices": sorted(out["devices"], key=str.lower),
        "usages": sorted(out["usages"], key=str.lower),
        "defs": out,
    }


# ── carrying the profiles themselves ─────────────────────────────────────────
# A template that stores only profile *names* can be applied to a project that
# already has those profiles and nowhere else. Ekahau ships a fixed set, but the
# interesting mixes use custom ones, and those are exactly the projects worth
# templating. So capture the objects, with whatever they depend on, and inject
# them where they are missing.

def _dep_ids(obj: dict):
    """Ids this object references. Ekahau spells them `somethingId(s)`."""
    for key, val in obj.items():
        if key == "id":
            continue
        if key.endswith("Id") and isinstance(val, str):
            yield val
        elif key.endswith("Ids") and isinstance(val, list):
            for v in val:
                if isinstance(v, str):
                    yield v


def _with_deps(index: dict, obj_id: str, seen=None) -> list:
    """An object and everything it points at, in dependency order.

    A usage profile names application profiles; copying it without them would
    write a reference to nothing. The walk is generic rather than a list of
    known fields, because the fields differ between Ekahau versions and a
    missed one fails silently inside the customer's project.
    """
    seen = set() if seen is None else seen
    if not obj_id or obj_id in seen:
        return []
    entry = index.get(obj_id)
    if not entry:
        return []
    seen.add(obj_id)
    out = []
    for dep in _dep_ids(entry["obj"]):
        out.extend(_with_deps(index, dep, seen))
    out.append({"member": entry["member"], "collection": entry["collection"],
                "obj": entry["obj"]})
    return out


def _capture_profile_defs(index: dict, rows: list, requirement_id) -> dict:
    """Full definitions for every profile the captured rows reference."""
    devices, usages = {}, {}
    for r in rows:
        for key, bucket in (("deviceProfileId", devices), ("usageProfileId", usages)):
            label = r["device"] if key == "deviceProfileId" else r["usage"]
            if label in bucket:
                continue
            chain = _with_deps(index, r.get(key))
            if chain:
                bucket[label] = chain
    return {
        "devices": devices,
        "usages": usages,
        "requirement": _with_deps(index, requirement_id) if requirement_id else [],
    }


def derive_template(extracted: dict, occupants, name: str) -> dict:
    """Turn captured counts into per-occupant ratios.

    `occupants` is what the source project was designed for. Everything is
    stored relative to it, so the template survives being applied to a building
    of a different size.
    """
    try:
        occupants = float(occupants)
    except (TypeError, ValueError):
        occupants = 0.0
    if occupants <= 0:
        return {"ok": False,
                "error": "Enter the number of people the source project was designed for - "
                         "the ratios are worked out against it."}

    rows = extracted.get("rows") or []
    if not rows:
        return {"ok": False,
                "error": "No capacity items found in that project. Set the areas up in "
                         "Ekahau first, then capture."}

    total = float(extracted.get("totalDevices") or 0)
    items = []
    for r in rows:
        items.append({
            "device": r["device"],
            "usage": r["usage"],
            # The number that actually gets applied: devices of this kind, per
            # person. Share is carried alongside purely so the saved file can
            # be read by eye.
            "perOccupant": round(r["deviceCount"] / occupants, 6),
            "shareOfTotal": round(r["deviceCount"] / total, 6) if total else 0.0,
            "capturedCount": r["deviceCount"],
        })

    return {
        "ok": True,
        "name": name or Path(extracted.get("source", "captured")).stem,
        "schema": 2,
        "capturedFrom": extracted.get("source", ""),
        "capturedOccupants": occupants,
        "requirementName": extracted.get("requirementName", ""),
        "devicesPerOccupant": round(total / occupants, 6),
        "items": items,
        # Schema 2 carries the profile objects. A schema 1 template still
        # applies - to a project that already has profiles by those names.
        "profileDefs": extracted.get("profileDefs") or {},
    }


def build_template(spec: dict) -> dict:
    """A template from rows typed in the editor, ready to save.

    `spec` carries `name`, `description`, `items` - each a device profile
    name, a usage profile name and devices per person - and `defs`, the
    profile objects the page has to hand (the open project's, and the ones
    the template being edited already carried). Only the definitions the
    rows use are kept.
    """
    name = str(spec.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "Give the template a name."}
    items, problems = [], []
    for i, row in enumerate(spec.get("items") or [], 1):
        device = str((row or {}).get("device") or "").strip()
        usage = str((row or {}).get("usage") or "").strip()
        try:
            per = float((row or {}).get("perOccupant"))
        except (TypeError, ValueError):
            per = -1.0
        if not device or not usage:
            problems.append("row %d needs both a device profile and a usage profile" % i)
            continue
        if per <= 0:
            problems.append("row %d needs a number of devices per person above 0" % i)
            continue
        items.append({"device": device, "usage": usage, "perOccupant": round(per, 6)})
    if problems:
        return {"ok": False, "error": "Not saved: " + "; ".join(problems) + "."}
    if not items:
        return {"ok": False, "error": "Add at least one device to the template."}

    total = sum(i["perOccupant"] for i in items)
    # Stored against 100 people so the saved file reads naturally by eye; it
    # is the per-person number that is applied.
    for i in items:
        i["shareOfTotal"] = round(i["perOccupant"] / total, 6) if total else 0.0
        i["capturedCount"] = round(i["perOccupant"] * 100, 2)

    defs = spec.get("defs") or {}
    dev_defs = (defs.get("devices") or {})
    use_defs = (defs.get("usages") or {})
    profile_defs = {
        "devices": {i["device"]: dev_defs[i["device"]] for i in items if dev_defs.get(i["device"])},
        "usages": {i["usage"]: use_defs[i["usage"]] for i in items if use_defs.get(i["usage"])},
        "requirement": defs.get("requirement") or [],
    }
    return {
        "ok": True,
        "name": name,
        "schema": 2,
        "description": str(spec.get("description") or "").strip(),
        "capturedFrom": str(spec.get("capturedFrom") or "built in Capacity"),
        "capturedOccupants": 100,
        "requirementName": str(spec.get("requirementName") or "Ekahau Best Practices"),
        "devicesPerOccupant": round(total, 6),
        "items": items,
        "profileDefs": profile_defs,
    }


def _device_count(exact: float) -> int:
    """Devices for a fractional count: half rounds up, as the page's
    ``Math.round`` does. ``round()`` rounds half to even, so 22.5 laptops
    were 22 in the file and 23 on the page."""
    return int(math.floor(exact + 0.5))


def apply_headcount(template: dict, occupants) -> dict:
    """Scale a template to a headcount. The only input at apply time."""
    try:
        occupants = float(occupants)
    except (TypeError, ValueError):
        occupants = 0.0
    if occupants <= 0:
        return {"ok": False, "error": "Enter how many people this building is for."}

    rows = []
    for item in template.get("items", []):
        exact = item.get("perOccupant", 0) * occupants
        rows.append({
            "device": item.get("device", ""),
            "usage": item.get("usage", ""),
            "deviceCount": _device_count(exact),
            "exact": exact,
        })
    return {
        "ok": True,
        "occupants": occupants,
        "rows": rows,
        "totalDevices": sum(r["deviceCount"] for r in rows),
    }


# ── storage ──────────────────────────────────────────────────────────────────
# Same split as the wall templates: shipped examples are read-only in the
# install tree, everything the user makes lives outside it so an update cannot
# touch it.

def _safe_filename(name: str) -> str:
    """Letters and digits of any script stay: keeping A-Z only sent every
    Cyrillic, Greek or CJK name to "capacity", so a second one was refused
    as a clash with the first. `templateFileFor` in capacity.js mirrors it."""
    stem = "".join(c for c in str(name)
                   if c.isalnum() or c in " _-").strip() or "capacity"
    return stem.replace(" ", "_") + TPL_SUFFIX


def list_templates() -> dict:
    out = []
    seen = set()
    for path in sorted(USER_DIR.glob("*" + TPL_SUFFIX)) if USER_DIR.is_dir() else []:
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        body["_file"] = path.name
        body["_builtin"] = False
        out.append(body)
        seen.add(path.name)
    for path in sorted(BUILTIN_DIR.glob("*" + TPL_SUFFIX)) if BUILTIN_DIR.is_dir() else []:
        if path.name in seen:
            continue
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        body["_file"] = path.name
        body["_builtin"] = True
        out.append(body)
    return {"ok": True, "templates": out, "folder": str(USER_DIR)}


def _same_file(a: Path, b: Path) -> bool:
    """True when two names reach one file.

    Not a name comparison. On Windows and macOS `Lab_1` and `lab_1` are one
    file, and asking whether the strings differ was how a case-only rename
    wrote the template and then deleted it as "the old one".
    """
    if a.name == b.name:
        return True
    try:
        return os.path.samefile(a, b)
    except OSError:
        return False


def save_template(template: dict, replaces: str | None = None) -> dict:
    """Write a template under its name, and never over a different one.

    `replaces` is the file this save stands in for - the template being
    edited. That file may be overwritten, and is removed when the name moved
    on; any other file at the target is another template, and the save is
    refused rather than writing over it. Names map to files through
    `_safe_filename`, which drops punctuation, so "Lab #1" and "Lab 1" are the
    same file and the refusal names the template already there.
    """
    if not template.get("items"):
        return {"ok": False, "error": "Nothing to save - the template has no capacity items."}
    USER_DIR.mkdir(parents=True, exist_ok=True)
    filename = _safe_filename(template.get("name", "capacity"))
    path = USER_DIR / filename
    old = USER_DIR / Path(replaces).name if replaces else None
    if old is not None and not old.is_file():
        old = None          # a shipped example, or already gone: nothing to remove
    same = old is not None and _same_file(old, path)
    if path.exists() and not same:
        try:
            there = json.loads(path.read_text(encoding="utf-8")).get("name") or filename
        except Exception:
            there = filename
        return {"ok": False, "exists": True,
                "error": f'A template called "{there}" already exists. '
                         f'Choose another name, or edit that one instead.'}
    if same and old.name != path.name:
        # A case-only rename. Renaming first carries the file across without a
        # moment in which neither name holds it.
        os.replace(old, path)
    body = dict(template)
    body.pop("_file", None)
    body.pop("_builtin", None)
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    if old is not None and not same:
        # Renamed in the editor: the old file goes, so one template does not
        # become two. Only after the new one is written.
        old.unlink()
    return {"ok": True, "file": filename, "path": str(path)}


def delete_template(filename: str) -> dict:
    path = USER_DIR / Path(filename).name
    try:
        path.resolve().relative_to(USER_DIR.resolve())
    except ValueError:
        return {"ok": False, "error": "Refusing to delete outside the template folder."}
    if not path.is_file():
        return {"ok": False, "error": "No such template."}
    path.unlink()
    return {"ok": True}


# ── where the requirement area goes ──────────────────────────────────────────
# Ekahau's own default is a rectangle covering the whole canvas. On a drawing
# with a title block and a wide border that applies the requirement across
# several times the actual building - on the project this was built against,
# the walls occupy 14.4% of the canvas.
#
# So the basis is the walls: the extent of the wall segments the designer drew,
# padded slightly. That reproduced a hand-drawn requirement area to within half
# a metre. The fallbacks descend in order of how directly they evidence where
# the building is.
#
# Deliberately NOT the trimmer's content_bounds(): that measures ink density
# and happily includes a title block, a north arrow and a border, which is the
# very thing this is avoiding.

AREA_PAD_M = 0.5
BASIS_ORDER = ("walls", "aps", "image", "canvas")


def _bbox(points):
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return {"x0": min(xs), "y0": min(ys), "x1": max(xs), "y1": max(ys)}


def _wall_points_for_floor(members, floor_id):
    """Endpoints of every wall segment on this floor, in plan units."""
    pts = {}
    for p in (members.get("wallPoints.json") or {}).get("wallPoints", []):
        loc = p.get("location") or {}
        if loc.get("floorPlanId") != floor_id:
            continue
        c = loc.get("coord") or {}
        if isinstance(c.get("x"), (int, float)) and isinstance(c.get("y"), (int, float)):
            pts[p.get("id")] = (float(c["x"]), float(c["y"]))
    if not pts:
        return []
    # Only points actually joined by a segment count. A stray wall point left
    # over from an edit would otherwise stretch the area to reach it.
    used = []
    segs = (members.get("wallSegments.json") or {}).get("wallSegments", [])
    for seg in segs:
        refs = seg.get("wallPoints") or []
        got = [pts[r] for r in refs if isinstance(r, str) and r in pts]
        if len(got) >= 2:
            used.extend(got)
    return used or list(pts.values())


def _ap_points_for_floor(members, floor_id):
    out = []
    for ap in (members.get("accessPoints.json") or {}).get("accessPoints", []):
        loc = ap.get("location") or {}
        if loc.get("floorPlanId") != floor_id:
            continue
        c = loc.get("coord") or {}
        if isinstance(c.get("x"), (int, float)) and isinstance(c.get("y"), (int, float)):
            out.append((float(c["x"]), float(c["y"])))
    return out


def area_for_floor(members, floor, image_bounds=None):
    """Decide the requirement rectangle for one floor plan.

    `image_bounds` is an optional {x0,y0,x1,y1} from whatever measured the
    bitmap; it is only consulted when there are neither walls nor APs.
    """
    fid = floor.get("id")
    width = float(floor.get("width") or 0)
    height = float(floor.get("height") or 0)
    mpu = floor.get("metersPerUnit")
    mpu = float(mpu) if isinstance(mpu, (int, float)) and mpu > 0 else None

    basis = None
    box = None

    walls = _wall_points_for_floor(members, fid)
    if len(walls) >= 2:
        basis, box = "walls", _bbox(walls)
    else:
        aps = _ap_points_for_floor(members, fid)
        if len(aps) >= 2:
            basis, box = "aps", _bbox(aps)
        elif image_bounds:
            basis, box = "image", dict(image_bounds)
        else:
            basis = "canvas"
            box = {"x0": 0.0, "y0": 0.0, "x1": width, "y1": height}

    # The pad is expressed in metres and converted, so it means the same thing
    # on plans drawn at different scales. Without metersPerUnit there is no
    # honest conversion, so it is left unpadded rather than guessed.
    pad_units = (AREA_PAD_M / mpu) if mpu else 0.0
    if basis != "canvas" and pad_units:
        box = {"x0": box["x0"] - pad_units, "y0": box["y0"] - pad_units,
               "x1": box["x1"] + pad_units, "y1": box["y1"] + pad_units}
    if width and height:
        box["x0"] = max(0.0, box["x0"]); box["y0"] = max(0.0, box["y0"])
        box["x1"] = min(width, box["x1"]); box["y1"] = min(height, box["y1"])

    w_units = max(0.0, box["x1"] - box["x0"])
    h_units = max(0.0, box["y1"] - box["y0"])
    canvas_area = width * height
    out = {
        "floorPlanId": fid,
        "floorName": floor.get("name") or "",
        "basis": basis,
        "padMeters": AREA_PAD_M if (basis != "canvas" and pad_units) else 0.0,
        "polygon": [
            {"x": box["x0"], "y": box["y0"]},
            {"x": box["x1"], "y": box["y0"]},
            {"x": box["x1"], "y": box["y1"]},
            {"x": box["x0"], "y": box["y1"]},
        ],
        "fractionOfCanvas": round((w_units * h_units) / canvas_area, 4) if canvas_area else None,
    }
    if mpu:
        w_m, h_m = w_units * mpu, h_units * mpu
        out["widthM"] = round(w_m, 2)
        out["heightM"] = round(h_m, 2)
        out["widthFt"] = round(w_m / 0.3048, 1)
        out["heightFt"] = round(h_m / 0.3048, 1)
        out["areaSqFt"] = round((w_m / 0.3048) * (h_m / 0.3048), 1)
    return out


def _polygon_area(area) -> float:
    """Shoelace, for picking the area he actually drew the requirement on."""
    pts = [p for p in (area.get("area") or []) if isinstance(p, dict)]
    if len(pts) < 3:
        return 0.0
    total = 0.0
    for i in range(len(pts)):
        a, b = pts[i], pts[(i + 1) % len(pts)]
        try:
            total += float(a.get("x", 0)) * float(b.get("y", 0))
            total -= float(b.get("x", 0)) * float(a.get("y", 0))
        except (TypeError, ValueError):
            return 0.0
    return abs(total) / 2.0


def _area_to_populate(areas):
    """Which drawn area on this floor should receive the capacity items.

    An area already marked as a requirement is the one he meant; failing that,
    the largest, because a requirement area covers the space being designed for
    and the small ones tend to be exclusions or annotations.
    """
    candidates = [a for a in areas if not a.get("capacityItems")]
    if not candidates:
        return None
    flagged = [a for a in candidates if a.get("requirementId")]
    pool = flagged or candidates
    return max(pool, key=_polygon_area)


def _basis_words(basis) -> str:
    return {
        "walls": "the walls you drew",
        "aps": "where the APs are",
        "image": "the floor plan image",
    }.get(basis, "the whole page")


def _floor_headcounts(floor_occupants) -> dict:
    """{floorPlanId: headcount} from whatever the caller sent.

    Blank, missing or unreadable means "use the project headcount" for that
    floor. Zero is a real answer - nobody works there - and leaves the floor
    alone rather than writing an area full of zeroes.
    """
    if isinstance(floor_occupants, str):
        try:
            floor_occupants = json.loads(floor_occupants) if floor_occupants.strip() else {}
        except ValueError:
            floor_occupants = {}
    out = {}
    for fid, value in (floor_occupants or {}).items() if isinstance(floor_occupants, dict) else ():
        if value is None or (isinstance(value, str) and not value.strip()):
            continue
        try:
            n = float(value)
        except (TypeError, ValueError):
            continue
        if n >= 0:
            out[str(fid)] = n
    return out


# What to do with a floor that already carries capacity items.
#
#   keep      leave it exactly as it is
#   devices   new device counts, outline kept
#   reshape   new device counts, outline redrawn from the walls or APs
#
# "Replace" used to rewrite only the first capacity area on a floor. Ekahau
# totals every capacity area on a floor, so any second one kept counting and
# each run added to the last. Both replacing choices now clear the device
# counts on every other capacity area on the floor - their outlines stay - so
# the floor ends up carrying exactly the number asked for.
EXISTING_CHOICES = ("keep", "devices", "reshape")


def _existing_choices(floor_existing) -> dict:
    if isinstance(floor_existing, str):
        try:
            floor_existing = json.loads(floor_existing) if floor_existing.strip() else {}
        except ValueError:
            floor_existing = {}
    if not isinstance(floor_existing, dict):
        return {}
    return {str(k): v for k, v in floor_existing.items() if v in EXISTING_CHOICES}


def _device_total(area) -> int:
    total = 0
    for item in area.get("capacityItems") or []:
        try:
            total += int(item.get("deviceCount") or 0)
        except (TypeError, ValueError, AttributeError):
            pass
    return total


def plan_application(esx_path, template, occupants, replace_existing=False,
                     floor_occupants=None, existing=None, floor_existing=None):
    """Work out what applying this template would do, without writing anything.

    One requirement area per floor plan. A floor that already has a requirement
    area is skipped unless asked otherwise - a hand-drawn area is real work and
    is never silently replaced.

    `occupants` is the headcount every floor gets by default. `floor_occupants`
    ({floorPlanId: headcount}) overrides it floor by floor: a building is
    rarely the same number of people on every storey, and one number applied
    to every floor puts the whole building on each of them.
    """
    esx_path = Path(esx_path)
    with zipfile.ZipFile(esx_path) as zf:
        members = _read_members(zf)

    default_existing = existing if existing in EXISTING_CHOICES else (
        "devices" if replace_existing else "keep")
    per_floor_existing = _existing_choices(floor_existing)
    per_floor = _floor_headcounts(floor_occupants)
    counts = apply_headcount(template, occupants)

    floors = [f for f in (members.get("floorPlans.json") or {}).get("floorPlans", [])
              if isinstance(f, dict) and f.get("id")]
    live = {f["id"] for f in floors}

    # The project headcount is only required where a floor falls back on it.
    if not counts.get("ok") and any(f["id"] not in per_floor for f in floors):
        return counts

    # Areas per live floor. Matched on floorPlanId only: `key` and the display
    # name both drift between Ekahau versions, and `isDefault` means "shipped
    # by Ekahau", not "the one in use".
    #
    # The distinction that matters is NOT whether an area exists - it is
    # whether that area already carries capacity items.
    #
    #   nothing drawn          create an area from the computed extent
    #   an area, no capacity   fill it in, keeping his polygon exactly
    #   an area with capacity  leave alone unless replacement is asked for
    #
    # Only the third discards anything he set. Treating all three as "already
    # has a requirement area" is what stopped a hand-drawn area - sixteen
    # vertices of real work - from ever being populated, which is the whole
    # reason he draws one.
    by_floor = {}
    orphans = 0
    for area in (members.get("areas.json") or {}).get("areas", []):
        if not isinstance(area, dict):
            continue
        fid = area.get("floorPlanId")
        if fid in live:
            by_floor.setdefault(fid, []).append(area)
        elif area.get("requirementId") or area.get("capacityItems"):
            orphans += 1

    plans = []
    for floor in floors:
        info = area_for_floor(members, floor)
        here = by_floor.get(floor["id"], [])
        with_capacity = [a for a in here if a.get("capacityItems")]
        target = _area_to_populate(here)

        own = per_floor.get(floor["id"])
        floor_counts = counts if own is None else (
            apply_headcount(template, own) if own > 0 else
            {"ok": True, "occupants": 0.0, "totalDevices": 0,
             "rows": [dict(r, deviceCount=0, exact=0.0)
                      for r in apply_headcount(template, 1)["rows"]]})
        info["occupants"] = floor_counts["occupants"]
        info["occupantsOverridden"] = own is not None

        if own == 0:
            info["mode"] = "none"
            info["skipped"] = True
            info["action"] = "skip - no people on this floor"
        elif with_capacity:
            choice = per_floor_existing.get(floor["id"], default_existing)
            primary = max(with_capacity, key=_polygon_area)
            info["mode"] = "replace"
            info["existingChoice"] = choice
            info["targetAreaId"] = primary.get("id")
            info["targetAreaName"] = primary.get("name") or ""
            info["existingItemCount"] = sum(
                len(a.get("capacityItems") or []) for a in with_capacity)
            info["existingDevices"] = sum(_device_total(a) for a in with_capacity)
            info["existingAreaCount"] = len(with_capacity)
            info["clearAreaIds"] = [a.get("id") for a in with_capacity
                                    if a is not primary]
            info["reshape"] = choice == "reshape"
            info["skipped"] = choice == "keep"
            if choice == "keep":
                info["action"] = ("keep - already has %d devices"
                                  % info["existingDevices"])
            elif choice == "devices":
                info["action"] = ("replace %d devices with %d, keep the outline"
                                  % (info["existingDevices"], floor_counts["totalDevices"]))
            else:
                info["action"] = ("replace %d devices with %d and redraw the "
                                  "outline from %s"
                                  % (info["existingDevices"], floor_counts["totalDevices"],
                                     _basis_words(info.get("basis"))))
            if choice != "keep" and len(with_capacity) > 1:
                info["action"] += (" - the other %d capacity areas are cleared "
                                   "so they stop adding to the total"
                                   % (len(with_capacity) - 1))
        elif target is not None:
            info["mode"] = "populate"
            info["targetAreaId"] = target.get("id")
            info["targetAreaName"] = target.get("name") or ""
            info["targetVertexCount"] = len(target.get("area") or [])
            info["skipped"] = False
            info["action"] = ("your area - adding %d capacity items, "
                              "your outline is not changed" % len(floor_counts["rows"]))
        else:
            info["mode"] = "create"
            info["skipped"] = False
            info["action"] = "create an area from %s" % _basis_words(info.get("basis"))

        # The outline the floor ends up with, for anything that draws it: a
        # new or redrawn area is the computed rectangle, anything else keeps
        # the polygon that is already there, vertex for vertex.
        kept = None
        if info["mode"] == "replace" and not info.get("reshape"):
            kept = primary
        elif info["mode"] == "populate":
            kept = target
        if kept is not None:
            info["outline"] = [{"x": p.get("x"), "y": p.get("y")}
                               for p in (kept.get("area") or [])
                               if isinstance(p, dict)]
        elif info["mode"] != "none":
            info["outline"] = [dict(p) for p in info["polygon"]]
        info["outlineIsNew"] = kept is None and info["mode"] != "none"

        # Kept for callers written against the old shape.
        info["hasExistingRequirement"] = bool(with_capacity)
        info["rows"] = floor_counts["rows"]
        info["totalDevices"] = floor_counts["totalDevices"]
        plans.append(info)

    # The profiles, resolved here rather than only in the writer.
    #
    # This is the whole reason the plan was worth changing. `apply_to` refuses
    # when the project does not carry the profiles the template names, and it
    # is right to refuse - capacity items pointing at profiles that are not in
    # the file open quietly wrong. But until this check existed here as well,
    # the *preview* knew nothing about it: it said "adding 6 capacity items",
    # the button offered to prepare, and the refusal arrived only after the
    # click. Measured against Ekahau's own samples, two of twenty did exactly
    # that - a green preview and then a 400.
    #
    # Resolution mutates: it injects any profile the template carries a
    # definition for. So the probe runs against a throwaway copy and the real
    # members are left untouched. `_read_members` parses only the JSON members,
    # so the copy is a few documents, not the floor plan images.
    names = counts if counts.get("ok") else apply_headcount(template, 1)
    if any(not p["skipped"] for p in plans):
        missing = _missing_for(copy.deepcopy(members), template, names)
        if missing:
            return {"ok": False, "missing": missing,
                    "error": _missing_message(missing),
                    "source": esx_path.name}

    writing = [p for p in plans if not p["skipped"]]
    return {
        "ok": True,
        "source": esx_path.name,
        # The project headcount and what it comes to on one floor. Where every
        # floor has its own number there is no project headcount, and these
        # describe nothing - hence the totals below.
        "occupants": counts.get("occupants", 0.0) if counts.get("ok") else 0.0,
        "totalDevices": counts["totalDevices"] if counts.get("ok") else 0,
        "rows": names["rows"] if counts.get("ok") else [],
        "perFloor": bool(per_floor),
        "existing": default_existing,
        "floorsWithDevices": sum(1 for p in plans if p.get("mode") == "replace"),
        "occupantsWritten": sum(p["occupants"] for p in writing),
        "devicesWritten": sum(p["totalDevices"] for p in writing),
        "floors": plans,
        "orphanAreasIgnored": orphans,
        "willWrite": sum(1 for p in plans if not p["skipped"]),
        "willSkip": sum(1 for p in plans if p["skipped"]),
    }


def _missing_for(members: dict, template: dict, counts: dict) -> list:
    """Which of the template's profiles this project cannot supply.

    The same three resolutions `apply_to` performs, in the same order, so the
    preview and the writer cannot disagree about whether a run is possible.
    Pass a copy: resolving creates profiles as a side effect.
    """
    defs = template.get("profileDefs") or {}
    id_map, created, missing = {}, [], []
    seen_device, seen_usage = set(), set()

    for row in counts["rows"]:
        if row["device"] not in seen_device:
            seen_device.add(row["device"])
            _got, miss = _resolve_profile(
                members, (defs.get("devices") or {}).get(row["device"]),
                row["device"], "deviceProfiles", id_map, created)
            if miss:
                missing.append(dict(miss, kind="device profile"))
        if row["usage"] not in seen_usage:
            seen_usage.add(row["usage"])
            _got, miss = _resolve_profile(
                members, (defs.get("usages") or {}).get(row["usage"]),
                row["usage"], "usageProfiles", id_map, created)
            if miss:
                missing.append(dict(miss, kind="usage profile"))

    req_name = template.get("requirementName") or ""
    if req_name:
        _got, req_missing = _resolve_profile(
            members, defs.get("requirement"), req_name,
            "requirements", id_map, created)
        if req_missing:
            missing.append(dict(req_missing, kind="requirement"))
    return missing


# ── the writer ───────────────────────────────────────────────────────────────
# Everything above this line reads. This is the only code in the module that
# changes a project, and the rules it works under are deliberate:
#
#   * A floor that already has a requirement area is left alone unless
#     replacement was explicitly asked for. Somebody drew that area.
#   * An area whose floor plan is gone is reported and otherwise untouched.
#   * The original is copied aside before it is overwritten, and the copy is
#     only ever removed by the user.
#   * Nothing is matched on `key`, on display name, or on `isDefault`.
#     `isDefault` means "Ekahau shipped it", not "this one is in use".

def _new_id() -> str:
    import uuid
    return str(uuid.uuid4())


def _collection_lookup(members: dict, collection: str) -> dict:
    """name -> id, for every object in a named collection anywhere in the file."""
    out = {}
    for body in members.values():
        if not isinstance(body, dict):
            continue
        for key, val in body.items():
            if key != collection or not isinstance(val, list):
                continue
            for obj in val:
                if not isinstance(obj, dict) or not isinstance(obj.get("id"), str):
                    continue
                label = _label_for({"obj": obj})
                if label:
                    out.setdefault(label, obj["id"])
    return out


def _inject(members: dict, chain: list, id_map: dict):
    """Add an object and its dependencies to the project. Returns its new id.

    Ids are rewritten as they are copied. Reusing the source project's ids
    would collide the moment a template is applied to the project it came from.
    """
    last = None
    for link in chain:
        old_id = link["obj"].get("id")
        if old_id in id_map:
            last = id_map[old_id]
            continue
        clone = json.loads(json.dumps(link["obj"]))
        clone["id"] = _new_id()
        # Point the copy at the copies of its dependencies.
        for key, val in list(clone.items()):
            if key == "id":
                continue
            if key.endswith("Id") and isinstance(val, str) and val in id_map:
                clone[key] = id_map[val]
            elif key.endswith("Ids") and isinstance(val, list):
                clone[key] = [id_map.get(v, v) for v in val]
        body = members.setdefault(link["member"], {})
        if not isinstance(body, dict):
            continue
        body.setdefault(link["collection"], []).append(clone)
        id_map[old_id] = clone["id"]
        last = clone["id"]
    return last


def _base_name(label: str) -> str:
    """A profile name with its qualifying suffix removed.

    Ekahau names the same stock profile differently across versions and across
    the panel it is read from: "Normal SLA (2 Mbps)" and "Normal SLA",
    "Conferencing, GoToMeeting" and "Conferencing", "Generic Wi-Fi 6E Laptop"
    and "Generic Wi-Fi 6E Laptop, Wi-Fi 6 2x2:2 160MHz". The stem before the
    comma or the bracket is the part that survives, so that is what a template
    captured on one project is matched on when applied to another.
    """
    s = str(label or "")
    s = re.sub(r"\s*\([^)]*\)\s*$", "", s)      # trailing "(2 Mbps)"
    s = s.split(",")[0]                          # ", GoToMeeting", ", Wi-Fi 6 2x2:2"
    return " ".join(s.split()).casefold()


def _resolve_profile(members, defs_chain, label, collection, id_map, created):
    """Find a profile by name in the target, or inject the captured one.

    Name, never id. Ekahau mints fresh uuids per project, so a template's ids
    exist nowhere but the project it was captured from; the name is the only
    thing that crosses. Exact first, then on the stem - and a stem that matches
    more than one profile is reported as ambiguous rather than guessed at,
    because picking one of two real profiles silently is how a project ends up
    quietly describing the wrong devices.
    """
    lookup = _collection_lookup(members, collection)
    existing = lookup.get(label)
    if existing:
        return existing, None

    stem = _base_name(label)
    if stem:
        hits = sorted({name for name in lookup if _base_name(name) == stem})
        if len(hits) == 1:
            return lookup[hits[0]], None
        if len(hits) > 1:
            return None, {"label": label, "reason": "ambiguous", "candidates": hits}

    if not defs_chain:
        return None, {"label": label, "reason": "absent", "candidates": []}
    new_id = _inject(members, defs_chain, id_map)
    if new_id:
        created.append(label)
    return new_id, None


def _missing_message(missing) -> str:
    """Say which profiles could not be resolved, and what to do about it."""
    ambiguous = [m for m in missing if m.get("reason") == "ambiguous"]
    absent = [m for m in missing if m.get("reason") != "ambiguous"]
    parts = []
    if absent:
        names = ", ".join("%s “%s”" % (m["kind"], m["label"]) for m in absent)
        parts.append(
            "This project does not have: " + names + ". "
            "Ekahau ships these as stock content in a new project, so if this is "
            "a project you have just created, check the names match what your "
            "Ekahau version calls them - they differ between releases. "
            "Otherwise add them in Ekahau, or open the template with Edit in "
            "Capacity while a project that has them is open and save it, so it "
            "carries its own copies."
        )
    for m in ambiguous:
        parts.append(
            "%s “%s” matches more than one profile in this project (%s). "
            "Rename the template's row, or the profiles, so one is meant."
            % (m["kind"], m["label"], ", ".join(m["candidates"]))
        )
    return " ".join(parts)


def apply_to(src_path, dest_path, template, occupants,
             replace_existing=False, floor_occupants=None,
             existing=None, floor_existing=None):
    """Write the template into a project. The only function here that writes.

    `src_path` is read and never modified - the written project is a separate
    file, which is the whole of the safety here: the original keeps its own
    name and needs no restoring. The new project is built in a temp file and
    moved into place in one step, so an interrupted write cannot leave a
    half-written .esx where a real project used to be.
    """
    import os
    import shutil
    import tempfile

    src_path = Path(src_path)
    dest_path = Path(dest_path)

    plan = plan_application(src_path, template, occupants, replace_existing,
                            floor_occupants=floor_occupants,
                            existing=existing, floor_existing=floor_existing)
    if not plan.get("ok"):
        return plan

    with zipfile.ZipFile(src_path) as zf:
        members = _read_members(zf)
        raw_names = [i.filename for i in zf.infolist()]

    # Profile names only; every floor's counts come from its own plan entry.
    counts = apply_headcount(template, occupants)
    if not counts.get("ok"):
        counts = dict(apply_headcount(template, 1), occupants=0.0, totalDevices=0)

    write_floors = [f for f in plan["floors"] if not f["skipped"]]
    if not write_floors:
        # Every floor was left alone. Returning here matters: resolving the
        # template's profiles injects any the project lacks, and a run that
        # writes no areas must not leave new profiles behind to explain.
        return {
            "ok": True, "source": src_path.name, "written": None,
            "occupants": counts["occupants"], "totalDevices": counts["totalDevices"],
            "rows": counts["rows"], "floorsWritten": [],
            "floorsSkipped": [f["floorName"] or f["floorPlanId"] for f in plan["floors"]],
            "areasReplaced": 0, "areasLeftInPlace": 0, "profilesCreated": [],
            "areasReshaped": 0, "areasCleared": 0,
            "orphanAreasIgnored": plan["orphanAreasIgnored"],
            "occupantsWritten": 0, "devicesWritten": 0,
            "note": "Every floor already has a requirement area or has nobody "
                    "on it, so nothing was written and the project was not "
                    "changed.",
        }

    defs = template.get("profileDefs") or {}
    id_map, created, missing = {}, [], []

    device_ids, usage_ids = {}, {}
    for row in counts["rows"]:
        if row["device"] not in device_ids:
            got, miss = _resolve_profile(
                members, (defs.get("devices") or {}).get(row["device"]),
                row["device"], "deviceProfiles", id_map, created)
            device_ids[row["device"]] = got
            if miss:
                missing.append(dict(miss, kind="device profile"))
        if row["usage"] not in usage_ids:
            got, miss = _resolve_profile(
                members, (defs.get("usages") or {}).get(row["usage"]),
                row["usage"], "usageProfiles", id_map, created)
            usage_ids[row["usage"]] = got
            if miss:
                missing.append(dict(miss, kind="usage profile"))

    req_name = template.get("requirementName") or ""
    req_id = None
    if req_name:
        req_id, req_missing = _resolve_profile(
            members, defs.get("requirement"), req_name, "requirements", id_map, created)
        if req_missing:
            missing.append(dict(req_missing, kind="requirement"))

    if missing:
        # Refusing is the right answer. Capacity items pointing at profiles the
        # file does not contain produce a project that opens and is quietly
        # wrong, which is worse than not writing at all. But the message has to
        # say which case this is: a name Ekahau ships under a slightly
        # different spelling is a different problem from a profile nobody has,
        # and "re-capture the template" is useless advice for the first.
        return {"ok": False, "missing": missing,
                "error": _missing_message(missing)}

    areas_body = members.get("areas.json")
    if not isinstance(areas_body, dict):
        areas_body = members["areas.json"] = {}
    areas = areas_body.setdefault("areas", [])

    target_ids = {f["floorPlanId"] for f in write_floors}

    # Replacement removes the area that was there rather than editing it, so a
    # half-overwritten area cannot be left behind.
    #
    # Only areas that actually carry capacity items are removed. An area with a
    # requirement and no capacity is a coverage zone somebody drew - a lobby, a
    # warehouse aisle - and replacing a capacity template is not permission to
    # delete it. On one real project this distinction is the difference between
    # removing one area and removing seven. Whatever is left standing is
    # counted and reported rather than passed over in silence.
    by_id = {a.get("id"): a for a in areas if isinstance(a, dict)}

    def items_for(floor):
        return [
            {
                "identifier": _new_id(),
                "deviceCount": row["deviceCount"],
                "usageProfileId": usage_ids[row["usage"]],
                "deviceProfileId": device_ids[row["device"]],
            }
            for row in floor["rows"] if row["deviceCount"] > 0
        ]

    # No area is ever deleted, in any of the three cases. Where one already
    # exists the items are written into it and the polygon, name, colour and
    # notes are left exactly as he drew them - replacing a capacity template is
    # not permission to redraw his outline, and on a hand-drawn requirement
    # area that outline is the work.
    replaced, populated, reshaped = 0, 0, 0
    cleared_ids = set()
    written = []
    for floor in write_floors:
        mode = floor.get("mode") or "create"
        target = by_id.get(floor.get("targetAreaId")) if floor.get("targetAreaId") else None

        if mode in ("populate", "replace") and target is not None:
            if target.get("capacityItems"):
                replaced += 1
            else:
                populated += 1
            target["capacityItems"] = items_for(floor)
            # His area keeps the requirement he gave it. The plan says only
            # devices are written into an area that is already there; putting
            # the template's requirement on it as well changed what the area
            # demands of the design without saying so. An area with none gets
            # the template's, since it has nothing to lose.
            if req_id and not target.get("requirementId"):
                target["requirementId"] = req_id
            if mode == "replace" and floor.get("reshape") and floor.get("polygon"):
                target["area"] = [{"x": p["x"], "y": p["y"]} for p in floor["polygon"]]
                reshaped += 1
            for other_id in floor.get("clearAreaIds") or []:
                other = by_id.get(other_id)
                if other is not None and other.get("capacityItems"):
                    other["capacityItems"] = []
                    cleared_ids.add(other_id)
        else:
            area = {
                "floorPlanId": floor["floorPlanId"],
                "name": template.get("name") or "Capacity",
                "noteIds": [],
                "capacityItems": items_for(floor),
                "color": "#2c3e50",
                "area": [{"x": p["x"], "y": p["y"]} for p in floor["polygon"]],
                "id": _new_id(),
                "status": "CREATED",
            }
            if req_id:
                area["requirementId"] = req_id
            areas.append(area)
        written.append(floor["floorName"] or floor["floorPlanId"])

    # Other areas on the floors written to: a lobby, an aisle, an exclusion.
    # Untouched, and said out loud so "replace" is never read as "delete
    # everything that was drawn here".
    touched = {f.get("targetAreaId") for f in write_floors if f.get("targetAreaId")}
    left_in_place = sum(
        1 for a in areas
        if isinstance(a, dict) and a.get("floorPlanId") in target_ids
        and a.get("id") not in touched and a.get("id") not in cleared_ids
        and a.get("requirementId") and not a.get("capacityItems"))

    # Build the new archive beside the destination first, so a failure part-way
    # through never lands on top of a real project.
    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".esx", dir=str(dest_path.parent))
    os.close(tmp_fd)
    try:
        with zipfile.ZipFile(src_path) as zin, \
                zipfile.ZipFile(tmp_name, "w", zipfile.ZIP_DEFLATED) as zout:
            for name in raw_names:
                if name in members:
                    continue  # a JSON member; rewritten below, changed or not
                zout.writestr(name, zin.read(name))
            for name, body in members.items():
                zout.writestr(name, json.dumps(body, indent=2))

        #: Built in a temp file and renamed over the top, so the destination
        #: is either entirely the old file or entirely the new one.
        os.replace(tmp_name, str(dest_path))
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)

    return {
        "ok": True,
        "source": src_path.name,
        "written": str(dest_path),
        "occupants": counts["occupants"],
        "totalDevices": counts["totalDevices"],
        "rows": counts["rows"],
        "floorsWritten": written,
        "perFloor": plan["perFloor"],
        "occupantsWritten": plan["occupantsWritten"],
        "devicesWritten": plan["devicesWritten"],
        "floorsSkipped": [f["floorName"] or f["floorPlanId"]
                          for f in plan["floors"] if f["skipped"]],
        "areasReplaced": replaced,
        "areasPopulated": populated,
        "areasReshaped": reshaped,
        "areasCleared": len(cleared_ids),
        "areasLeftInPlace": left_in_place,
        "profilesCreated": created,
        "orphanAreasIgnored": plan["orphanAreasIgnored"],
    }
