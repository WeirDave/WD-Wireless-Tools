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

import json
import re
import zipfile
from pathlib import Path

USER_DIR = Path.home() / ".wd_wireless_tools" / "capacity"
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
            "deviceCount": int(round(exact)),
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
    stem = re.sub(r"[^A-Za-z0-9 _-]+", "", str(name)).strip() or "capacity"
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


def save_template(template: dict) -> dict:
    if not template.get("items"):
        return {"ok": False, "error": "Nothing to save - the template has no capacity items."}
    USER_DIR.mkdir(parents=True, exist_ok=True)
    filename = _safe_filename(template.get("name", "capacity"))
    path = USER_DIR / filename
    body = dict(template)
    body.pop("_file", None)
    body.pop("_builtin", None)
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")
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


def plan_application(esx_path, template, occupants, replace_existing=False):
    """Work out what applying this template would do, without writing anything.

    One requirement area per floor plan. A floor that already has a requirement
    area is skipped unless asked otherwise - a hand-drawn area is real work and
    is never silently replaced.
    """
    esx_path = Path(esx_path)
    with zipfile.ZipFile(esx_path) as zf:
        members = _read_members(zf)

    counts = apply_headcount(template, occupants)
    if not counts.get("ok"):
        return counts

    floors = [f for f in (members.get("floorPlans.json") or {}).get("floorPlans", [])
              if isinstance(f, dict) and f.get("id")]
    live = {f["id"] for f in floors}

    # Which floors already carry a requirement. Matched on floorPlanId only:
    # `key` and the display name both drift between Ekahau versions, and
    # `isDefault` means "shipped by Ekahau", not "the one in use".
    existing = set()
    orphans = 0
    for area in (members.get("areas.json") or {}).get("areas", []):
        if not isinstance(area, dict):
            continue
        if not (area.get("requirementId") or area.get("capacityItems")):
            continue
        fid = area.get("floorPlanId")
        if fid in live:
            existing.add(fid)
        else:
            orphans += 1

    plans = []
    for floor in floors:
        info = area_for_floor(members, floor)
        already = floor["id"] in existing
        info["hasExistingRequirement"] = already
        info["skipped"] = already and not replace_existing
        info["action"] = ("skip - already has a requirement area" if info["skipped"]
                          else "replace existing" if already else "create")
        info["rows"] = counts["rows"]
        info["totalDevices"] = counts["totalDevices"]
        plans.append(info)

    return {
        "ok": True,
        "source": esx_path.name,
        "occupants": counts["occupants"],
        "totalDevices": counts["totalDevices"],
        "rows": counts["rows"],
        "floors": plans,
        "orphanAreasIgnored": orphans,
        "willWrite": sum(1 for p in plans if not p["skipped"]),
        "willSkip": sum(1 for p in plans if p["skipped"]),
    }


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


def _resolve_profile(members, defs_chain, label, collection, id_map, created):
    """Find a profile by name in the target, or inject the captured one."""
    existing = _collection_lookup(members, collection).get(label)
    if existing:
        return existing, None
    if not defs_chain:
        return None, label
    new_id = _inject(members, defs_chain, id_map)
    if new_id:
        created.append(label)
    return new_id, None


def apply_to(src_path, dest_path, template, occupants,
             replace_existing=False, backup=True):
    """Write the template into a project. The only function here that writes.

    `src_path` is read and never modified. When `dest_path` is an existing
    file it is copied aside first, and the new project is moved into place in
    one step, so an interrupted write cannot leave a half-written .esx where a
    real project used to be.
    """
    import os
    import shutil
    import tempfile
    from datetime import datetime

    src_path = Path(src_path)
    dest_path = Path(dest_path)

    plan = plan_application(src_path, template, occupants, replace_existing)
    if not plan.get("ok"):
        return plan

    with zipfile.ZipFile(src_path) as zf:
        members = _read_members(zf)
        raw_names = [i.filename for i in zf.infolist()]

    counts = apply_headcount(template, occupants)

    write_floors = [f for f in plan["floors"] if not f["skipped"]]
    if not write_floors:
        # Every floor was left alone. Returning here matters: resolving the
        # template's profiles injects any the project lacks, and a run that
        # writes no areas must not leave new profiles behind to explain.
        return {
            "ok": True, "source": src_path.name, "written": None, "backup": None,
            "occupants": counts["occupants"], "totalDevices": counts["totalDevices"],
            "rows": counts["rows"], "floorsWritten": [],
            "floorsSkipped": [f["floorName"] or f["floorPlanId"] for f in plan["floors"]],
            "areasReplaced": 0, "areasLeftInPlace": 0, "profilesCreated": [],
            "orphanAreasIgnored": plan["orphanAreasIgnored"],
            "note": "Every floor already has a requirement area, so nothing was "
                    "written and the project was not changed.",
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
                missing.append("device profile “%s”" % miss)
        if row["usage"] not in usage_ids:
            got, miss = _resolve_profile(
                members, (defs.get("usages") or {}).get(row["usage"]),
                row["usage"], "usageProfiles", id_map, created)
            usage_ids[row["usage"]] = got
            if miss:
                missing.append("usage profile “%s”" % miss)

    req_name = template.get("requirementName") or ""
    req_id = None
    if req_name:
        req_id, req_missing = _resolve_profile(
            members, defs.get("requirement"), req_name, "requirements", id_map, created)
        if req_missing:
            missing.append("requirement “%s”" % req_missing)

    if missing:
        # Refusing is the right answer. Capacity items pointing at profiles the
        # file does not contain produce a project that opens and is quietly
        # wrong, which is worse than not writing at all.
        return {"ok": False, "missing": missing,
                "error": "This template does not carry definitions for, and the target "
                         "project does not have: " + ", ".join(missing)
                         + ". Re-capture the template from its source project, or add "
                           "those profiles in Ekahau first."}

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
    replaced, left_in_place = 0, 0
    if replace_existing and target_ids:
        keep = []
        for area in areas:
            if isinstance(area, dict) and area.get("floorPlanId") in target_ids:
                if area.get("capacityItems"):
                    replaced += 1
                    continue
                if area.get("requirementId"):
                    left_in_place += 1
            keep.append(area)
        areas[:] = keep

    written = []
    for floor in write_floors:
        area = {
            "floorPlanId": floor["floorPlanId"],
            "name": template.get("name") or "Capacity",
            "noteIds": [],
            "capacityItems": [
                {
                    "identifier": _new_id(),
                    "deviceCount": row["deviceCount"],
                    "usageProfileId": usage_ids[row["usage"]],
                    "deviceProfileId": device_ids[row["device"]],
                }
                for row in counts["rows"] if row["deviceCount"] > 0
            ],
            "color": "#2c3e50",
            "area": [{"x": p["x"], "y": p["y"]} for p in floor["polygon"]],
            "id": _new_id(),
            "status": "CREATED",
        }
        if req_id:
            area["requirementId"] = req_id
        areas.append(area)
        written.append(floor["floorName"] or floor["floorPlanId"])

    # Build the new archive beside the destination first, so a failure part-way
    # through never lands on top of a real project.
    tmp_fd, tmp_name = tempfile.mkstemp(suffix=".esx", dir=str(dest_path.parent))
    os.close(tmp_fd)
    backup_path = None
    try:
        with zipfile.ZipFile(src_path) as zin, \
                zipfile.ZipFile(tmp_name, "w", zipfile.ZIP_DEFLATED) as zout:
            for name in raw_names:
                if name in members:
                    continue  # a JSON member; rewritten below, changed or not
                zout.writestr(name, zin.read(name))
            for name, body in members.items():
                zout.writestr(name, json.dumps(body, indent=2))

        if backup and dest_path.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = dest_path.with_name(
                "%s.backup-%s%s" % (dest_path.stem, stamp, dest_path.suffix))
            shutil.copy2(str(dest_path), str(backup_path))
        os.replace(tmp_name, str(dest_path))
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)

    return {
        "ok": True,
        "source": src_path.name,
        "written": str(dest_path),
        "backup": str(backup_path) if backup_path else None,
        "occupants": counts["occupants"],
        "totalDevices": counts["totalDevices"],
        "rows": counts["rows"],
        "floorsWritten": written,
        "floorsSkipped": [f["floorName"] or f["floorPlanId"]
                          for f in plan["floors"] if f["skipped"]],
        "areasReplaced": replaced,
        "areasLeftInPlace": left_in_place,
        "profilesCreated": created,
        "orphanAreasIgnored": plan["orphanAreasIgnored"],
    }
