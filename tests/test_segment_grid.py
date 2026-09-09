"""How many sections a floor is split into, and the unit bug that broke it.

`computeAntennaGrid` sized the split from `W * H * 10.7639` - plan units times
the square feet in a square metre, as though a plan unit were a metre. It is
not: a length in plan units becomes metres only after multiplying by that
plan's own `metersPerUnit`, about 0.025 on a CAD import.

So a 10000x7500 plan was measured as 807 million square feet instead of half a
million - out by a factor of 1584 - and every plan of any size hit the 24-cell
cap. Segmentation therefore never adapted to anything:

    1,708 sq ft apartment    ->  24 sections
    509,616 sq ft office     ->  24 sections
    2,170,002 sq ft warehouse->  24 sections

The density term never influenced the answer either, because the size term
always won. Construction asking for "fewer pages with more on them" was asking
for this to work, not for a different default - which is why the threshold is
left where it is here and only the arithmetic is corrected.

Corrected, the same plans give 1, 6 and 20 sections.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"
NODE_TIMEOUT_S = 120

PRELUDE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('var SEG_SQFT_PER_PAGE');
const b = src.indexOf('function segCellLabel');
if (a < 0 || b < 0) throw new Error('computeAntennaGrid block not found');
eval(src.slice(a, b));
function cells(W, H, n, mpu, opts) {
  const g = computeAntennaGrid(W, H, new Array(n).fill({}), opts || {}, mpu);
  return g.cols * g.rows;
}
const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class SegmentGrid(unittest.TestCase):
    def check(self, body: str):
        program = PRELUDE + "eval(" + json.dumps(body) + ");"
        r = subprocess.run(["node", "-e", program, str(REPORT_JS)],
                           capture_output=True, text=True, timeout=NODE_TIMEOUT_S)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr).strip())

    def test_the_split_follows_the_size_of_the_building(self):
        """The whole bug in one assertion: three buildings three orders of
        magnitude apart must not all get the same answer."""
        self.check("""
          const flat = cells(496, 800, 6, 0.02);          // ~1,700 sq ft
          const office = cells(10000, 7500, 8, 0.025125); // ~510,000 sq ft
          const shed = cells(14000, 9000, 18, 0.04);      // ~2,170,000 sq ft
          check('an apartment was split at all: ' + flat, flat === 1);
          check('office and warehouse got the same split: '
                + office + ' vs ' + shed, office !== shed);
          check('the split does not grow with the building: '
                + [flat, office, shed], flat < office && office < shed);
          done();
        """)

    def test_a_cad_import_no_longer_saturates_the_cap(self):
        """24 was the cap, and every plan reached it."""
        self.check("""
          const n = cells(10000, 7500, 8, 0.025125);
          check('still pinned to the cap: ' + n, n < 24);
          check('unreasonably coarse instead: ' + n, n >= 2);
          done();
        """)

    def test_plan_units_are_not_treated_as_metres(self):
        """The same plan at two different scales is two different buildings."""
        self.check("""
          const fine = cells(10000, 7500, 8, 0.005);   // ~20,000 sq ft
          const coarse = cells(10000, 7500, 8, 0.05);  // ~2,000,000 sq ft
          check('scale made no difference: ' + fine + ' vs ' + coarse,
                fine !== coarse);
          check('the smaller building got more sections', fine < coarse);
          done();
        """)

    def test_without_a_scale_it_falls_back_to_ap_density(self):
        """There is no honest way to know how big a building is without one,
        and guessing is what caused this."""
        self.check("""
          const few = cells(10000, 7500, 5, undefined);
          const many = cells(10000, 7500, 60, undefined);
          check('no scale still produced a size-based split: ' + few, few === 1);
          check('density was ignored without a scale: ' + many, many > 1);
          done();
        """)

    def test_an_explicit_grid_still_wins(self):
        """Whatever he sets by hand in the grid dialog is the answer."""
        self.check("""
          const n = cells(10000, 7500, 8, 0.025125, { segCols: 2, segRows: 3 });
          check('a hand-set grid was overridden: ' + n, n === 6);
          done();
        """)

    def test_the_two_halves_of_the_decision_are_named(self):
        """Area per sheet and APs per sheet are different arguments and should
        be arguable separately."""
        src = REPORT_JS.read_text(encoding="utf-8")
        for name in ("SEG_SQFT_PER_PAGE", "SEG_APS_PER_PAGE", "SEG_MAX_CELLS"):
            self.assertIn(name, src)

    def test_every_caller_passes_the_scale(self):
        """A caller that forgets it silently gets the density-only fallback,
        which looks plausible and is wrong."""
        src = REPORT_JS.read_text(encoding="utf-8")
        calls = [l for l in src.splitlines() if "computeAntennaGrid(" in l
                 and "function computeAntennaGrid" not in l]
        self.assertGreaterEqual(len(calls), 4)
        for line in calls:
            with self.subTest(line=line.strip()):
                self.assertIn("metersPerUnit", line)


if __name__ == "__main__":
    unittest.main()
