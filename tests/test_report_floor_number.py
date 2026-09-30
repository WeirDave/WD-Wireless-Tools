"""The Report's "Floor N" heading names the storey, not Ekahau's stack slot.

`buildingFloors[].floorNumber` counts a building's floors from 0 by stacking
position. The Report printed it as it stood, so a plan named "Floor 1" was
headed "Floor 0" and "Floor 3" was headed "Floor 2" - on the sheets an
installer uses to find the right floor. This runs the real `floorNumberFor`
and `segFloorHeading` out of report.js against the real WD.storeyNumber.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"
SHARED_JS = ROOT / "web" / "assets" / "js" / "wd-shared.js"

PRELUDE = r"""
const fs = require('fs');
const report = fs.readFileSync(process.argv[1], 'utf8');
const shared = fs.readFileSync(process.argv[2], 'utf8');
function cut(src, from) {
  const a = src.indexOf(from);
  if (a < 0) throw new Error('moved: ' + from);
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    if (src[b] === '{') { depth++; seen = true; }
    else if (src[b] === '}') depth--;
    b++;
  }
  return src.slice(a, b);
}
globalThis.WD = {};
eval(cut(shared, '  WD.storeyNumber = function') + ';');
eval(cut(report, '  function floorNumberFor(fp) {'));
eval(cut(report, '  function segFloorHeading(opts) {'));
let proj = { buildingFloors: {} };
function heading(fp) {
  return segFloorHeading({ floorNumber: floorNumberFor(fp), floorName: fp.name });
}
const failures = [];
function eq(what, got, want) {
  if (got !== want) failures.push(what + ': got ' + JSON.stringify(got)
    + ', wanted ' + JSON.stringify(want));
}
"""

EPILOGUE = r"""
if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheHeadingNamesTheStorey(unittest.TestCase):

    def run_block(self, checks: str):
        r = subprocess.run(
            ["node", "-e", PRELUDE + "eval(" + json.dumps(checks) + ");" + EPILOGUE,
             str(REPORT_JS), str(SHARED_JS)],
            capture_output=True, encoding="utf-8", timeout=120)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())

    def test_the_reported_case(self):
        self.run_block("""
          proj.buildingFloors = {
            f1: { floorPlanId: 'f1', floorNumber: 0 },
            f3: { floorPlanId: 'f3', floorNumber: 2 },
          };
          eq('first floor', heading({ id: 'f1', name: 'Floor 1' }), 'Floor 1');
          eq('third floor', heading({ id: 'f3', name: 'Floor 3' }), 'Floor 3');
        """)

    def test_an_unnumbered_name_in_a_building_counts_from_one(self):
        self.run_block("""
          proj.buildingFloors = { g: { floorPlanId: 'g', floorNumber: 0 } };
          eq('ground', heading({ id: 'g', name: 'Ground' }), 'Floor 1');
        """)

    def test_no_building_and_no_number_keeps_the_plan_name(self):
        self.run_block("""
          proj.buildingFloors = {};
          eq('plain', heading({ id: 'x', name: 'Warehouse' }), 'Warehouse');
          eq('unplaced', floorNumberFor({ id: '_none', name: 'Floor 2' }), null);
        """)


if __name__ == "__main__":
    unittest.main()
