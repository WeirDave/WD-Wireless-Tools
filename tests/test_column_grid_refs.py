"""Column grid references — two clicks, and what they can and cannot answer.

A warehouse section page shows an AP floating in empty slab with nothing to
locate it against. Crews locate everything off the column grid, so a grid
reference is the coordinate system they already have.

**The grid is declared rather than read.** Nothing here looks at the raster:
finding the bubbles would need circle detection, OCR and line tracing, and a
mis-read bubble produces a confidently wrong reference that the installer has
no way to catch. Two labelled intersections is the whole input.

These run the real functions out of ``report.js`` rather than reading its
source, and the arithmetic is checked against grids built to known spacings so
a sign error or an off-by-one bay fails rather than merely looking plausible.
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
const source = fs.readFileSync(process.argv[1], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
const block = slice('function gridColumnIndex(label)', '\n  window.WDGrid');
globalThis.window = globalThis;

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function eq(what, got, want) {
  if (got !== want) failures.push(what + '\n     got:  ' + JSON.stringify(got)
                                 + '\n     want: ' + JSON.stringify(want));
}
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
"""


def run_block(checks: str) -> subprocess.CompletedProcess:
    program = PRELUDE + "eval(block + " + json.dumps(checks) + ");"
    try:
        return subprocess.run(["node", "-e", program, str(REPORT_JS)],
                              capture_output=True, text=True,
                              encoding="utf-8", timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(f"node did not finish within {NODE_TIMEOUT_S}s") from exc


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class GridLabels(unittest.TestCase):
    def check(self, checks: str):
        result = run_block(checks)
        self.assertEqual(result.returncode, 0,
                         (result.stdout + result.stderr).strip())

    def test_letters_count_the_way_drawings_do(self):
        """A building past 26 lines carries on AA, AB - the same sequence a
        spreadsheet uses, which is what drawings do."""
        self.check("""
          eq('A', gridColumnIndex('A'), 0);
          eq('Z', gridColumnIndex('Z'), 25);
          eq('AA', gridColumnIndex('AA'), 26);
          eq('AB', gridColumnIndex('AB'), 27);
          eq('BA', gridColumnIndex('BA'), 52);
          for (var i = 0; i < 800; i++) {
            eq('round trip ' + i, gridColumnIndex(gridColumnLabel(i)), i);
          }
          done();
        """)

    def test_lower_case_and_nonsense_are_handled_rather_than_guessed_at(self):
        self.check("""
          eq('lower case', gridColumnIndex('c'), 2);
          eq('a number', gridColumnIndex('4'), null);
          eq('mixed', gridColumnIndex('A1'), null);
          eq('empty', gridColumnIndex(''), null);
          eq('nothing', gridColumnIndex(null), null);
          done();
        """)

    def test_a_label_is_read_however_it_is_written(self):
        """Drawings write it every one of these ways and the difference is not
        meaningful."""
        self.check("""
          ['A-1', 'A1', 'a 1', 'A_1', 'A/1', '  A-1  '].forEach(function (t) {
            const p = parseGridLabel(t);
            check('"' + t + '" did not parse', p && p.col === 0 && p.row === 1);
          });
          eq('AA-12', JSON.stringify(parseGridLabel('AA-12')), '{"col":26,"row":12}');
          eq('no letter', parseGridLabel('-4'), null);
          eq('no number', parseGridLabel('C'), null);
          eq('junk', parseGridLabel('hello'), null);
          done();
        """)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class GridArithmetic(unittest.TestCase):
    def check(self, checks: str):
        result = run_block(checks)
        self.assertEqual(result.returncode, 0,
                         (result.stdout + result.stderr).strip())

    def test_a_grid_built_to_known_spacings_reads_back_exactly(self):
        """The whole feature, in one assertion. Lines A..H every 100 units
        across and 1..9 every 80 down, calibrated off two of its own
        intersections, then every intersection asked for its own name back."""
        self.check("""
          const COL = 100, ROW = 80, X0 = 250, Y0 = 130;
          const at = (c, r) => ({ x: X0 + c * COL, y: Y0 + (r - 1) * ROW });
          const a = Object.assign({ col: 0, row: 1 }, at(0, 1));
          const b = Object.assign({ col: 6, row: 7 }, at(6, 7));
          const s = buildGridSolver(a, b, 'x');
          check('solver refused a clean grid: ' + s.reason, s.ok);
          for (var c = 0; c < 8; c++) {
            for (var r = 1; r <= 9; r++) {
              const p = at(c, r);
              eq('intersection ' + gridColumnLabel(c) + '-' + r,
                 gridRefForPoint(s, p.x, p.y), gridColumnLabel(c) + '-' + r);
            }
          }
          done();
        """)

    def test_a_point_inside_a_bay_reads_as_the_nearest_intersection(self):
        """Which is how a grid reference is spoken. An AP is rarely on a
        column; it is in the bay, and the reference sends somebody to the
        nearest thing they can stand under."""
        self.check("""
          const a = { x: 0, y: 0, col: 0, row: 1 };
          const b = { x: 600, y: 480, col: 6, row: 7 };
          const s = buildGridSolver(a, b, 'x');
          check('refused', s.ok);
          // Bay C..D is x 200..300; y row 3..4 is 160..240.
          eq('just past C', gridRefForPoint(s, 210, 165), 'C-3');
          eq('just short of D', gridRefForPoint(s, 290, 235), 'D-4');
          // Exactly mid-bay has to break the tie somewhere, and JavaScript's
          // Math.round takes the higher line. Pinned because it is arbitrary:
          // if it ever changes, it should change on purpose.
          eq('dead centre takes the higher line', gridRefForPoint(s, 250, 200), 'D-4');
          done();
        """)

    def test_the_letters_can_run_either_way_and_the_answer_differs(self):
        """Two labelled points are equally consistent with letters running
        across the plan or down it, which is why the picker offers the switch
        rather than guessing. If both settings gave the same answer the switch
        would be decoration."""
        self.check("""
          const a = { x: 0, y: 0, col: 0, row: 1 };
          const b = { x: 600, y: 480, col: 6, row: 7 };
          const alongX = buildGridSolver(a, b, 'x');
          const alongY = buildGridSolver(a, b, 'y');
          check('x refused', alongX.ok);
          check('y refused', alongY.ok);
          eq('letters across', gridRefForPoint(alongX, 300, 80), 'D-2');
          eq('letters down', gridRefForPoint(alongY, 300, 80), 'B-4');
          done();
        """)

    def test_a_grid_running_right_to_left_still_works(self):
        """Letters do not always increase left to right, and a sign error here
        would put every AP in the wrong half of the building."""
        self.check("""
          const a = { x: 600, y: 0, col: 0, row: 1 };
          const b = { x: 0, y: 480, col: 6, row: 7 };
          const s = buildGridSolver(a, b, 'x');
          check('refused: ' + s.reason, s.ok);
          eq('A is on the right', gridRefForPoint(s, 600, 0), 'A-1');
          eq('G is on the left', gridRefForPoint(s, 0, 480), 'G-7');
          eq('D is in the middle', gridRefForPoint(s, 300, 240), 'D-4');
          done();
        """)

    def test_labels_that_do_not_start_at_a_or_one(self):
        """A grid whose first line is C, or whose numbering starts at 4, is an
        ordinary drawing - usually a building section lifted out of a bigger
        sheet."""
        self.check("""
          const a = { x: 100, y: 100, col: 2, row: 4 };
          const b = { x: 500, y: 400, col: 6, row: 7 };
          const s = buildGridSolver(a, b, 'x');
          check('refused: ' + s.reason, s.ok);
          eq('the first point', gridRefForPoint(s, 100, 100), 'C-4');
          eq('the second point', gridRefForPoint(s, 500, 400), 'G-7');
          // The origin of the drawing is not the origin of the grid: line A
          // sits one bay to the left of x=0 here, so x=0 is column B.
          eq('the drawing origin is inside the grid', gridRefForPoint(s, 0, 0), 'B-3');
          done();
        """)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class GridRefusals(unittest.TestCase):
    """What it will not answer, and says so.

    The rule the whole feature is written around: a reference that is quietly
    wrong is worse than no reference, because the installer cannot tell.
    """

    def check(self, checks: str):
        result = run_block(checks)
        self.assertEqual(result.returncode, 0,
                         (result.stdout + result.stderr).strip())

    def test_two_points_on_one_line_are_refused_with_a_reason(self):
        self.check("""
          const sameCol = buildGridSolver(
            { x: 0, y: 0, col: 3, row: 1 }, { x: 0, y: 400, col: 3, row: 7 }, 'x');
          check('same lettered line was accepted', !sameCol.ok);
          check('no reason given', /same lettered line/.test(sameCol.reason));

          const sameRow = buildGridSolver(
            { x: 0, y: 0, col: 0, row: 4 }, { x: 400, y: 0, col: 6, row: 4 }, 'x');
          check('same numbered line was accepted', !sameRow.ok);
          check('no reason given', /same numbered line/.test(sameRow.reason));
          done();
        """)

    def test_two_clicks_almost_on_top_of_each_other_are_refused(self):
        """A mis-click, not a building: any error in either point is then
        multiplied across the whole plan."""
        self.check("""
          const s = buildGridSolver(
            { x: 100, y: 100, col: 0, row: 1 },
            { x: 102, y: 103, col: 6, row: 7 }, 'x', { w: 1600, h: 1200 });
          check('a three-pixel bay was accepted', !s.ok);
          check('no reason given: ' + s.reason, /too close together/.test(s.reason));
          done();
        """)

    def test_the_separation_guard_is_measured_against_the_plan(self):
        """A floor plan is in whatever units it was authored in - a raster in
        thousands of pixels, a vector import in single figures - so a fixed
        threshold means something different on every drawing.

        The same two points are a mis-click on a large plan and the whole
        building on a small one, and the guard has to agree with that. It did
        not: written as "less than one plan unit" it refused every grid on any
        plan whose coordinates run 0..1, which is what a floor plan with no
        declared width falls back to.
        """
        self.check("""
          const a = { x: 0.0, y: 0.0, col: 0, row: 1 };
          const b = { x: 0.6, y: 0.48, col: 4, row: 5 };
          const small = buildGridSolver(a, b, 'x', { w: 1, h: 1 });
          check('a grid across a small plan was refused: ' + small.reason, small.ok);
          const large = buildGridSolver(a, b, 'x', { w: 1600, h: 1200 });
          check('the same two points on a large plan were accepted', !large.ok);
          done();
        """)

    def test_with_no_plan_size_there_is_no_separation_guard(self):
        """A number that cannot be interpreted is worse than none: without the
        floor's own dimensions there is nothing to call "close" relative to."""
        self.check("""
          const s = buildGridSolver(
            { x: 100, y: 100, col: 0, row: 1 },
            { x: 102, y: 103, col: 6, row: 7 }, 'x');
          check('refused with nothing to measure against: ' + s.reason, s.ok);
          done();
        """)

    def test_a_missing_point_is_refused_rather_than_throwing(self):
        self.check("""
          [[null, null], [{ x: 0, y: 0, col: 0, row: 1 }, null],
           [null, { x: 1, y: 1, col: 1, row: 2 }]].forEach(function (pair) {
            const s = buildGridSolver(pair[0], pair[1], 'x');
            check('accepted a missing point', !s.ok);
            check('no reason', !!s.reason);
          });
          done();
        """)

    def test_an_unsolved_grid_produces_no_reference_at_all(self):
        """Not a blank, not a zero, not "A-1" - nothing, so the column shows a
        dash and nobody reads a bay number off a grid that was never set."""
        self.check("""
          eq('refused solver', gridRefForPoint({ ok: false }, 10, 10), '');
          eq('no solver', gridRefForPoint(null, 10, 10), '');
          eq('undefined', gridRefForPoint(undefined, 10, 10), '');
          done();
        """)

    def test_a_point_off_the_grid_gives_nothing_rather_than_a_negative_bay(self):
        """An AP outside the lettered area - in a yard, or on a mezzanine drawn
        beyond the frame - has no grid reference. "Z-0" would be a reference to
        a place that does not exist."""
        self.check("""
          const s = buildGridSolver(
            { x: 100, y: 100, col: 0, row: 1 },
            { x: 700, y: 580, col: 6, row: 7 }, 'x');
          check('refused: ' + s.reason, s.ok);
          eq('left of line A', gridRefForPoint(s, -400, 100), '');
          eq('above line 1', gridRefForPoint(s, 100, -400), '');
          done();
        """)
