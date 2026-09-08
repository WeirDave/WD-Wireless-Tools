"""Find walls modelled floor-to-ceiling that should stop short of it.

An Ekahau wall type with no ``upperEdge`` is Auto height: the engine treats it
as reaching the ceiling.  That is right for a wall and wrong for furniture, and
the error is not small.  ``Shelf, Warehouse`` is 18 dB/m over 1.5 m of
thickness - 27 dB - so on Auto it models steel racking from the slab to the roof
of a high-bay.  Signal that in reality passes over the top is predicted as
blocked, which moves AP counts rather than nudging a heat map.

What decides "should have a height" is the type's *name*, not its attenuation.
A name is something a person can argue with; a guess from the numbers is not.
Anything whose name says what it is - shelf, rack, cubicle, pod - and which is
actually drawn on a plan gets reported.

Severity is the total attenuation multiplied by how many segments carry it.
Fifty-two segments of 27 dB is a different problem from four, and the point of
the report is to say which drawing to fix first.

Repair follows the trimmer's posture: back up before writing, touch nothing but
the field being corrected, and refuse anything that cannot be verified.
"""
from __future__ import annotations

import json
import re
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

FT = 0.3048

# Objects that stand on the floor and stop short of the ceiling.
PARTIAL_HEIGHT_NAME = re.compile(
    r"shelf|shelv|rack|cubicle|bookshelf|partition|pod\b|booth|counter|"
    r"bin\b|pallet|display|fixture",
    re.I)

# Deliberately full height, so never reported as missing one.
#
# A Framery pod is a sealed box: metal roof, metal floor, a footprint of a
# square metre or two. Height-limiting it would let a ray from a ceiling AP
# drop in over the top at no loss, which is the opposite of what its metal roof
# does, and the question people ask of a pod is whether signal reaches someone
# inside it. Over-attenuating two square metres of floor is the cheaper error.
#
# This is the opposite call from shelving on purpose: a long open-topped run
# with a large footprint should be height-limited, a small sealed enclosure
# should not.
DELIBERATELY_FULL_HEIGHT = re.compile(r"framery", re.I)

# A height stated in the type's own name - "Warehouse Rack Wall - 16ft".
NAME_STATES_HEIGHT = re.compile(r"(\d+(?:\.\d+)?)\s*(ft|foot|feet|'|m)\b", re.I)

# Heights for types we ship or Ekahau ships, so a repair can offer a value
# rather than only a complaint.
KNOWN_HEIGHTS_M = {
    "cubicle": 1.5,
    "shelf, retail": 2.5,
    "retail shelf": 2.5,
    "shelf, warehouse": 10.0,
    "warehouse shelf": 10.0,
    "bookshelf": 2.0,
    "restaurant seating": 1.5,
    "market stall": 2.5,
}


@dataclass
class Finding:
    project: Path
    wall_type: str
    segments: int
    db_total: float
    thickness: float
    suggested_m: float | None
    suggestion_source: str

    @property
    def severity(self) -> float:
        """How much wrongly-modelled attenuation this puts on the plan."""
        return self.db_total * self.segments

    @property
    def suggested_ft(self) -> float | None:
        return None if self.suggested_m is None else self.suggested_m / FT


@dataclass
class ProjectReport:
    path: Path
    findings: list[Finding] = field(default_factory=list)
    error: str = ""

    @property
    def severity(self) -> float:
        return sum(f.severity for f in self.findings)


def _five_ghz_db_per_m(wall_type: dict) -> float:
    for p in wall_type.get("propagationProperties") or []:
        if p.get("band") == "FIVE":
            return float(p.get("attenuationFactor") or 0.0)
    return 0.0


def _suggest_height(name: str) -> tuple[float | None, str]:
    """A height to offer, and where it came from.

    A number in the name beats a lookup: someone wrote it there on purpose.
    Nothing is invented - a type whose name says nothing gets no suggestion,
    because inventing one is how the shipped templates went wrong.
    """
    m = NAME_STATES_HEIGHT.search(name)
    if m:
        value = float(m.group(1))
        unit = m.group(2).lower()
        metres = value if unit == "m" else value * FT
        return round(metres, 4), f"stated in the name ({m.group(0).strip()})"
    known = KNOWN_HEIGHTS_M.get(name.strip().lower())
    if known is not None:
        return known, "the height Ekahau uses for this type"
    return None, "no height in the name and no known equivalent - needs a decision"


def audit_project(path: Path) -> ProjectReport:
    report = ProjectReport(path=path)
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "wallTypes.json" not in names:
                return report
            types = {w.get("id"): w
                     for w in json.loads(z.read("wallTypes.json"))["wallTypes"]}
            segments = (json.loads(z.read("wallSegments.json"))["wallSegments"]
                        if "wallSegments.json" in names else [])
    except (OSError, zipfile.BadZipFile, KeyError, ValueError) as e:
        report.error = f"could not be read: {e}"
        return report

    used: dict[str, int] = {}
    for s in segments:
        tid = s.get("wallTypeId")
        if tid:
            used[tid] = used.get(tid, 0) + 1

    for tid, count in used.items():
        w = types.get(tid)
        if not w:
            continue
        name = w.get("name") or ""
        if "upperEdge" in w:
            continue                       # already has a height
        if not PARTIAL_HEIGHT_NAME.search(name):
            continue                       # nothing about it says partial height
        if DELIBERATELY_FULL_HEIGHT.search(name):
            continue                       # sealed on top; see the note above
        thickness = float(w.get("thickness") or 0.0)
        suggested, why = _suggest_height(name)
        report.findings.append(Finding(
            project=path, wall_type=name, segments=count,
            db_total=_five_ghz_db_per_m(w) * thickness, thickness=thickness,
            suggested_m=suggested, suggestion_source=why))

    report.findings.sort(key=lambda f: -f.severity)
    return report


def audit_folder(folder: Path) -> list[ProjectReport]:
    reports = [audit_project(p) for p in sorted(Path(folder).rglob("*.esx"))]
    hits = [r for r in reports if r.findings or r.error]
    hits.sort(key=lambda r: -r.severity)
    return hits


def repair_project(path: Path, heights: dict[str, float],
                   backup: bool = True) -> dict:
    """Set ``upperEdge`` on the named wall types, and nothing else.

    ``heights`` maps wall-type name to metres.  A type already carrying a
    height is left alone; a name that is not in the file is reported rather
    than ignored, because a silent no-op looks like success.
    """
    path = Path(path)
    if not path.is_file():
        return {"error": f"No such project: {path}"}
    if not heights:
        return {"error": "No heights given, so there is nothing to change."}

    try:
        with zipfile.ZipFile(path) as z:
            members = {n: z.read(n) for n in z.namelist()}
    except (OSError, zipfile.BadZipFile) as e:
        return {"error": f"Could not read the project: {e}"}
    if "wallTypes.json" not in members:
        return {"error": "This project has no wallTypes.json to correct."}

    try:
        doc = json.loads(members["wallTypes.json"])
        types = doc["wallTypes"]
    except (ValueError, KeyError) as e:
        return {"error": f"wallTypes.json could not be parsed: {e}"}

    wanted = {k.strip().lower(): v for k, v in heights.items()}
    changed, skipped = [], []
    for w in types:
        key = (w.get("name") or "").strip().lower()
        if key not in wanted:
            continue
        if "upperEdge" in w:
            skipped.append({"name": w.get("name"), "why": "already has a height",
                            "upperEdge": w["upperEdge"]})
            continue
        upper = float(wanted[key])
        if upper <= float(w.get("lowerEdge") or 0.0):
            return {"error": f"{w.get('name')!r}: a top of {upper} m is not "
                             "above its bottom."}
        rebuilt: dict = {}
        for k, v in w.items():
            rebuilt[k] = v
            if k == "lowerEdge":
                rebuilt["upperEdge"] = upper
        if "upperEdge" not in rebuilt:
            rebuilt["upperEdge"] = upper
        w.clear()
        w.update(rebuilt)
        changed.append({"name": rebuilt.get("name"), "upperEdge": upper})

    missing = sorted(set(wanted) - {(w.get("name") or "").strip().lower()
                                    for w in types})
    if not changed:
        return {"error": "Nothing was changed - none of those wall types needed "
                         "a height in this project.", "skipped": skipped,
                "notFound": missing}

    backup_path = None
    if backup:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_path = path.with_name(f"{path.stem}.previous-{stamp}{path.suffix}")
        try:
            shutil.copy2(path, backup_path)
        except OSError as e:
            return {"error": f"Could not back the project up, so nothing was "
                             f"changed: {e}"}

    members["wallTypes.json"] = (json.dumps(doc, indent=2, ensure_ascii=False)
                                 + "\n").encode("utf-8")
    tmp = path.with_suffix(path.suffix + ".wd-audit.tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as out:
            for name, blob in members.items():
                out.writestr(name, blob)
        tmp.replace(path)
    except OSError as e:
        tmp.unlink(missing_ok=True)
        if backup_path:
            backup_path.unlink(missing_ok=True)
        return {"error": f"Write failed, the project was not changed: {e}"}

    return {"ok": True, "path": str(path),
            "backup": str(backup_path) if backup_path else None,
            "changed": changed, "skipped": skipped, "notFound": missing}


# Runnable from an installed copy, because `scripts/` is not in the release
# payload and this is the tool someone needs when their delivered drawings may
# be wrong:
#
#     python -m tools.wall_audit "C:\Users\me\Ekahau Projects"
#     python -m tools.wall_audit <folder> --fix
def _cli(argv: list[str]) -> int:
    import sys
    args = [a for a in argv if not a.startswith("-")]
    if not args:
        print(__doc__)
        return 2
    folder = Path(args[0])
    if not folder.is_dir():
        print(f"Not a folder: {folder}")
        return 2

    reports = [r for r in audit_folder(folder) if r.findings]
    if not reports:
        print("Nothing to correct: every partial-height wall type in use "
              "already carries a height.")
        return 0

    segments = sum(f.segments for r in reports for f in r.findings)
    print(f"{len(reports)} project(s) draw furniture at full height "
          f"- {segments} wall segments in total. Worst first.\n")
    for r in reports:
        print(f"  {r.path.name}   (severity {r.severity:.0f})")
        for f in r.findings:
            where = ("no height to suggest - needs a decision"
                     if f.suggested_m is None
                     else f"suggest {f.suggested_m:.2f} m ({f.suggested_ft:.0f} ft)")
            print(f"     {f.wall_type:<28} {f.segments:>4} segments  "
                  f"{f.db_total:>5.1f} dB   {where}")
        print()

    if "--fix" not in argv:
        print("Nothing was written. Re-run with --fix to set the heights above.")
        return 0

    print("Correcting. The previous copy of each project is kept beside it.\n")
    failed = 0
    for r in reports:
        heights = {f.wall_type: f.suggested_m for f in r.findings
                   if f.suggested_m is not None}
        if not heights:
            print(f"  {r.path.name}: skipped, nothing with a defensible height")
            continue
        res = repair_project(r.path, heights)
        if res.get("error"):
            failed += 1
            print(f"  {r.path.name}: {res['error']}")
        else:
            for c in res["changed"]:
                print(f"  {r.path.name}: {c['name']} -> {c['upperEdge']:.2f} m")
            print(f"     kept {Path(res['backup']).name}")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_cli(sys.argv[1:]))
