"""Prepare a project in one pass: trim the canvas, put the requirement areas
in, load the wall types.

Today those are three separate errands. He pulls the floor plans in, saves,
opens PlanTrim, saves, opens Quick Walls, saves, and only then starts drawing.
Each of those is a load and a save of a file that can run to a couple of
hundred megabytes. This does the whole set from one load and one save.

**The order is not a preference, and it is not left to the caller.**

Trimming decides where to crop by unioning the drawing's ink bounds with the
bounding box of every coordinate that belongs to the floor - see
``esx_trimmer._floor_coord_bbox``. A requirement area is a coordinate carrier.
So an area injected before the trim is unioned into the crop and holds it open,
and an area that fell back to the canvas basis - the whole plan, which is
exactly what happens on a fresh floor with no walls drawn yet - holds it open
to the full sheet. The trimmer then finds that the content "already fills 100%
of the canvas" and skips, reporting a clean skip for a crop it was silently
prevented from making.

That failure leaves no mark. The file opens, every floor is present, and the
plan is simply the size it always was. So the order is enforced twice over: the
steps are sorted into ``STEP_ORDER`` and then the sequence about to run is
checked against ``ORDER_RULES`` before anything is written. A rule that is only
written down in a comment is a rule that gets reordered by someone reading the
comment as background.

**Re-running is the normal case, not the exception.** He runs this, opens the
project in Ekahau, draws walls, and runs it again. So:

* Wall types already in the project are left alone (``wall_inject``).
* A floor already trimmed reports as already filled and is skipped
  (``esx_trimmer``).
* A floor that already has a requirement area is left alone
  (``capacity_profiles``) - with one deliberate exception below.

The exception is the point of re-running. The first pass runs on a plan with no
walls and no APs, so the requirement area has nothing to measure and falls back
to the whole canvas. Once he has drawn walls, the area *should* tighten to the
wall extent. Only an area this pass could have produced is replaced, and only
one shape counts as that: a polygon that is still exactly the canvas rectangle.
Anything else - a polygon he nudged, redrew, or cut around an atrium - is his
work and is never touched, which is why the recogniser is deliberately the
conservative half of the problem rather than a guess at provenance.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from datetime import datetime
from pathlib import Path

from tools import capacity_profiles, esx_trimmer, wall_inject

#: The one place execution order is decided.
STEP_ORDER = ("trim", "areas", "walls")

#: Constraints that must hold whatever ``STEP_ORDER`` says. Each is
#: (earlier, later, why) and is checked against the actual sequence before a
#: run starts, so reordering ``STEP_ORDER`` fails loudly instead of quietly.
ORDER_RULES = (
    ("trim", "areas",
     "A requirement area is a coordinate carrier, and the trimmer unions every "
     "one of a floor's coordinates into the crop box. An area injected first "
     "holds the crop open - to the whole sheet when it fell back to the canvas "
     "basis - and the trim then skips as though there were nothing to crop."),
)


class PrepOrderError(RuntimeError):
    """The steps were about to run in an order that would break one of them."""


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


def _check_order(sequence) -> None:
    seq = list(sequence)
    for earlier, later, why in ORDER_RULES:
        if earlier not in seq or later not in seq:
            continue
        if seq.index(earlier) > seq.index(later):
            raise PrepOrderError(
                f"'{earlier}' must run before '{later}', and this run had them "
                f"as {seq}. {why}")


def resolve_steps(steps=None) -> list:
    """Put the requested steps into the order they have to run in.

    Callers ask for a set of steps, never a sequence. Accepting a sequence
    would mean accepting a wrong one.
    """
    wanted = set(STEP_ORDER if steps is None else steps)
    unknown = wanted - set(STEP_ORDER)
    if unknown:
        raise ValueError(f"unknown preparation step(s): {sorted(unknown)}")
    ordered = [s for s in STEP_ORDER if s in wanted]
    _check_order(ordered)
    return ordered


# ── reading, for the parts this module decides itself ────────────────────────

def _members(path: Path) -> dict:
    with zipfile.ZipFile(path) as z:
        return capacity_profiles._read_members(z)


def _floors(members: dict) -> list:
    return [f for f in (members.get("floorPlans.json") or {}).get("floorPlans", [])
            if isinstance(f, dict) and f.get("id")]


def _is_canvas_rectangle(polygon, floor, tol: float = 0.5) -> bool:
    """Is this polygon still exactly the canvas, corner for corner?

    That is the one shape this pass produces when it has nothing to measure,
    and the one shape nobody draws on purpose. Half a pixel of tolerance,
    which is float noise from a crop and a JSON round trip and nothing else -
    a corner anybody moved on purpose moved further than that.
    """
    w = float(floor.get("width") or 0)
    h = float(floor.get("height") or 0)
    if not (w and h) or not isinstance(polygon, list) or len(polygon) != 4:
        return False
    want = {(0.0, 0.0), (w, 0.0), (w, h), (0.0, h)}
    got = []
    for p in polygon:
        if not isinstance(p, dict):
            return False
        try:
            got.append((float(p["x"]), float(p["y"])))
        except (KeyError, TypeError, ValueError):
            return False
    for gx, gy in got:
        if not any(abs(gx - wx) <= tol and abs(gy - wy) <= tol for wx, wy in want):
            return False
    return True


def stale_placeholder_areas(members: dict) -> list:
    """Areas this pass made on a bare plan that a re-run can now do better.

    Two conditions, both required. The polygon must still be the whole canvas,
    which is what the area falls back to when there is nothing to measure and
    is the only shape that can be told apart from his own work. And there must
    now be something better to measure: walls, or failing that APs. Without the
    second condition a re-run would replace the area with an identical one and
    call it progress.
    """
    out = []
    floors = {f["id"]: f for f in _floors(members)}
    for area in (members.get("areas.json") or {}).get("areas", []):
        if not isinstance(area, dict) or not area.get("capacityItems"):
            continue
        floor = floors.get(area.get("floorPlanId"))
        if not floor:
            continue
        if not _is_canvas_rectangle(area.get("area"), floor):
            continue
        basis = capacity_profiles.area_for_floor(members, floor).get("basis")
        if basis in ("walls", "aps"):
            out.append({"areaId": area.get("id"),
                        "floorPlanId": floor["id"],
                        "floorName": floor.get("name") or "",
                        "newBasis": basis})
    return out


def _drop_areas(src: Path, dest: Path, area_ids: set) -> None:
    """Copy the project across without the named areas.

    Deleting rather than editing, for the reason the capacity writer gives:
    a half-overwritten area is worse than a missing one, and the writer is
    about to create the replacement anyway.
    """
    with zipfile.ZipFile(src) as z:
        raw = {n: z.read(n) for n in z.namelist()}
    body = json.loads(raw["areas.json"].decode("utf-8"))
    body["areas"] = [a for a in body.get("areas", [])
                     if not (isinstance(a, dict) and a.get("id") in area_ids)]
    raw["areas.json"] = (json.dumps(body, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    with zipfile.ZipFile(dest, "w", zipfile.ZIP_DEFLATED) as out:
        for name, blob in raw.items():
            out.writestr(name, blob)


# ── the preview ──────────────────────────────────────────────────────────────

def plan(esx_path, steps=None, wall_types=None, template=None, occupants=None,
         margin: int = esx_trimmer.DEFAULT_MARGIN, boxes=None,
         retighten: bool = True) -> dict:
    """What a run would do, without writing anything.

    Each step is previewed by the module that owns it, so the preview cannot
    drift from the work. The one thing it cannot do is preview a step against
    what an earlier step will have changed - the trim moves every coordinate on
    a floor it crops - so the area figures here are measured against the file
    as it stands and are marked as such.
    """
    path = Path(esx_path)
    if not path.is_file():
        return {"ok": False, "error": f"No such project: {path}"}
    try:
        order = resolve_steps(steps)
    except (ValueError, PrepOrderError) as exc:
        return {"ok": False, "error": str(exc)}

    out = {"ok": True, "source": path.name, "steps": order, "step": {}}

    if "trim" in order:
        try:
            report = esx_trimmer.analyze(path, margin=margin, boxes=boxes)
            out["step"]["trim"] = esx_trimmer._report_json(report)
        except esx_trimmer.TrimError as exc:
            out["step"]["trim"] = {"ok": False, "error": str(exc)}

    if "areas" in order:
        if not template:
            out["step"]["areas"] = {"ok": False,
                                    "error": "No capacity template was chosen."}
        else:
            area_plan = capacity_profiles.plan_application(path, template, occupants)
            if retighten and area_plan.get("ok"):
                stale = stale_placeholder_areas(_members(path))
                area_plan["retighten"] = stale
                by_floor = {s["floorPlanId"]: s for s in stale}
                for floor in area_plan.get("floors", []):
                    hit = by_floor.get(floor.get("floorPlanId"))
                    if hit and floor.get("skipped"):
                        floor["skipped"] = False
                        floor["action"] = (
                            "tighten - the area still covers the whole plan and "
                            f"there are now {hit['newBasis']} to measure")
                area_plan["willWrite"] = sum(
                    1 for f in area_plan.get("floors", []) if not f["skipped"])
                area_plan["willSkip"] = sum(
                    1 for f in area_plan.get("floors", []) if f["skipped"])
            area_plan["measuredBeforeTrim"] = "trim" in order
            out["step"]["areas"] = area_plan

    if "walls" in order:
        if not wall_types:
            out["step"]["walls"] = {"ok": False,
                                    "error": "No wall template was chosen."}
        else:
            out["step"]["walls"] = wall_inject.plan_injection(path, wall_types)

    return out


# ── the run ──────────────────────────────────────────────────────────────────

def run(esx_path, dest=None, steps=None, wall_types=None, template=None,
        occupants=None, margin: int = esx_trimmer.DEFAULT_MARGIN, boxes=None,
        retighten: bool = True, backup: bool = True) -> dict:
    """Do the whole pass and write once.

    Each step reads the file the previous step produced, which is what makes
    this a pass rather than three errands: the areas are measured on the
    trimmed canvas, not the original one. Those intermediates live in a
    temporary directory and are never seen - one file goes in, one comes out,
    and if any step refuses, nothing is written at all.
    """
    src = Path(esx_path)
    if not src.is_file():
        return {"ok": False, "error": f"No such project: {src}"}
    try:
        order = resolve_steps(steps)
    except (ValueError, PrepOrderError) as exc:
        return {"ok": False, "error": str(exc)}

    target = Path(dest) if dest else src
    result = {"ok": True, "source": src.name, "steps": order,
              "ran": [], "step": {}, "changed": False}

    tmpdir = Path(tempfile.mkdtemp(prefix="wd-prep-"))
    try:
        cur = src
        seq = 0

        def nxt():
            nonlocal seq
            seq += 1
            return tmpdir / f"stage{seq}{src.suffix}"

        for step in order:
            result["ran"].append(step)

            if step == "trim":
                try:
                    out = nxt()
                    report = esx_trimmer.trim(cur, dest=out, margin=margin, boxes=boxes)
                except esx_trimmer.TrimError as exc:
                    return {"ok": False, "error": f"Trimming refused: {exc}",
                            "ran": result["ran"]}
                result["step"]["trim"] = esx_trimmer._report_json(report)
                if report.trimmed_count:
                    cur = out
                    result["changed"] = True

            elif step == "areas":
                if not template:
                    return {"ok": False, "ran": result["ran"],
                            "error": "No capacity template was chosen, so nothing "
                                     "was written."}
                dropped = []
                staged = cur
                if retighten:
                    dropped = stale_placeholder_areas(_members(cur))
                    result["step"]["retighten"] = dropped
                    if dropped:
                        out = nxt()
                        _drop_areas(cur, out, {s["areaId"] for s in dropped})
                        staged = out
                out = nxt()
                report = capacity_profiles.apply_to(
                    staged, out, template, occupants, replace_existing=False,
                    backup=False)
                if not report.get("ok"):
                    return {"ok": False, "ran": result["ran"],
                            "error": report.get("error", "The requirement areas "
                                                         "could not be written."),
                            "step": {"areas": report}}
                result["step"]["areas"] = report
                if report.get("written"):
                    cur = out
                    result["changed"] = True
                elif dropped:
                    # The removals are only ever a step on the way to the
                    # replacements. Keeping them without the areas that were
                    # supposed to take their place would delete his capacity
                    # data and call the run a success.
                    return {"ok": False, "ran": result["ran"],
                            "error": "The areas that cover the whole plan were "
                                     "cleared to be re-measured, but nothing was "
                                     "written to replace them, so the project was "
                                     "left exactly as it was.",
                            "step": {"areas": report}}

            elif step == "walls":
                if not wall_types:
                    return {"ok": False, "ran": result["ran"],
                            "error": "No wall template was chosen, so nothing "
                                     "was written."}
                out = nxt()
                report = wall_inject.inject(cur, wall_types, dest=out, backup=False)
                if report.get("error"):
                    return {"ok": False, "ran": result["ran"],
                            "error": report["error"], "step": {"walls": report}}
                result["step"]["walls"] = report
                if report.get("written"):
                    cur = out
                    result["changed"] = True

        # Belt and braces: the sequence that actually ran, checked against the
        # rules rather than against what it was supposed to be.
        _check_order(result["ran"])

        if not result["changed"]:
            result.update(written=False, path=None, backup=None,
                          note="This project is already prepared - nothing to "
                               "trim, no areas to add and no wall types "
                               "missing - so it was left as it is.")
            return result

        backup_path = None
        if backup and target.exists():
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            backup_path = target.with_name(
                f"{target.stem}.previous-{stamp}{target.suffix}")
            shutil.copy2(target, backup_path)

        shutil.move(str(cur), str(target))
        # Written; an older generation is expendable now, not before.
        if backup_path:
            _prune_backups(target, protect=str(backup_path))
        result.update(written=True, path=str(target),
                      backup=str(backup_path) if backup_path else None)
        return result
    finally:
        shutil.rmtree(tmpdir, ignore_errors=True)
