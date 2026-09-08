#!/usr/bin/env python3
"""Which projects model furniture as floor-to-ceiling.

    python scripts/audit_walls.py "C:\\Users\\me\\Ekahau Projects"
    python scripts/audit_walls.py <folder> --fix

Without --fix nothing is written; it reads every .esx it can find and prints
what it would change.  With --fix it sets the height on the types it has a
defensible number for, keeping the previous copy of each project beside it.

A type with no height in its name and no known equivalent is never given one
automatically - it is listed for a decision instead.  Guessing a height is what
put the wrong values in the shipped templates in the first place.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.wall_audit import audit_folder, repair_project  # noqa: E402

FT = 0.3048


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    do_fix = "--fix" in sys.argv
    if not args:
        print(__doc__)
        return 2

    folder = Path(args[0])
    if not folder.is_dir():
        print(f"Not a folder: {folder}")
        return 2

    print(f"Reading .esx projects under {folder}\n")
    reports = audit_folder(folder)

    unreadable = [r for r in reports if r.error]
    reports = [r for r in reports if r.findings]

    if not reports:
        print("Nothing to correct: every partial-height wall type in use "
              "already carries a height.")
        if unreadable:
            print(f"\n{len(unreadable)} project(s) could not be read:")
            for r in unreadable:
                print(f"   {r.path.name}: {r.error}")
        return 0

    total_segments = sum(f.segments for r in reports for f in r.findings)
    print(f"{len(reports)} project(s) draw furniture at full height "
          f"- {total_segments} wall segments in total.")
    print("Worst first: attenuation multiplied by how many segments carry it.\n")

    for r in reports:
        print(f"  {r.path.name}")
        for f in r.findings:
            height = ("no height to suggest" if f.suggested_m is None
                      else f"suggest {f.suggested_m:.2f} m ({f.suggested_ft:.0f} ft)")
            print(f"     {f.wall_type:<28} {f.segments:>4} segments  "
                  f"{f.db_total:>5.1f} dB each   {height}")
            print(f"     {'':<28} {'':>4}           {'':>5}          "
                  f"  {f.suggestion_source}")
        print(f"     {'':<28} {'':>4}           severity {r.severity:.0f}\n")

    undecidable = [(r, f) for r in reports for f in r.findings
                   if f.suggested_m is None]
    if undecidable:
        print("Needs a decision - no height in the name, no known equivalent:")
        for r, f in undecidable:
            print(f"   {f.wall_type}  in  {r.path.name}")
        print()

    if not do_fix:
        print("Nothing was written. Re-run with --fix to set the heights above.")
        return 0

    print("Correcting projects. The previous copy of each is kept beside it.\n")
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
            continue
        names = ", ".join(f"{c['name']} -> {c['upperEdge']:.2f} m"
                          for c in res["changed"])
        print(f"  {r.path.name}: {names}")
        print(f"     kept {Path(res['backup']).name}")

    if unreadable:
        print(f"\n{len(unreadable)} project(s) could not be read and were left "
              "alone.")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
