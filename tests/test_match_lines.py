"""Match lines at section edges.

The companion to the Key Plan, and the standard AEC pair: the key plan answers
"where am I in the building", the match line answers "where does this drawing
continue" at the edge where the reader runs out of paper. Standard name, dashed
along the shared edge, labelled with the section that carries on - which is how
a run of racking is followed from sheet to sheet.

The rule that matters is which edges get one. A section with no APs is never
given a page, so an edge onto an empty section leads nowhere: marking it would
promise a sheet that does not exist. The building perimeter gets nothing for the
same reason.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"
CSS = ROOT / "web" / "assets" / "wd-tools.css"
NODE_TIMEOUT_S = 120

PRELUDE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function slice(from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('not found: ' + from);
  return src.slice(a, b);
}
const block = slice('function segCellLabel(col, row)', '\n  function renderAntennaSegmentedOverview')
            + slice('function matchLinesFor(cell, cells, cW, cH)', '\n  function renderAntennaSegmentCell');
globalThis.WD = { esc: (s) => String(s) };

// A grid of cells; `filled` lists the ones that have APs and therefore pages.
function grid(cols, rows, filled) {
  const cells = [];
  for (let r = 0; r < rows; r++)
    for (let c = 0; c < cols; c++)
      cells.push({ col: c, row: r, x0: c * 100, y0: r * 100,
                   x1: (c + 1) * 100, y1: (r + 1) * 100,
                   aps: filled.indexOf(c + ',' + r) > -1 ? [{}] : [] });
  return cells;
}
const at = (cells, c, r) => cells.filter(x => x.col === c && x.row === r)[0];
const refs = (out) => (out.match(/SECTION ([A-Z]\d+)/g) || []).map(s => s.replace('SECTION ', ''));
const lines = (out) => (out.match(/class="rep-matchline"/g) || []).length;

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class MatchLines(unittest.TestCase):
    def check(self, body: str):
        program = PRELUDE + "eval(block + " + json.dumps(body) + ");"
        r = subprocess.run(["node", "-e", program, str(REPORT_JS)],
                           capture_output=True, text=True, timeout=NODE_TIMEOUT_S)
        self.assertEqual(r.returncode, 0, (r.stdout + r.stderr).strip())

    def test_an_interior_section_is_marked_on_every_side_that_continues(self):
        self.check("""
          const cells = grid(3, 3, ['0,0','1,0','2,0','0,1','1,1','2,1','0,2','1,2','2,2']);
          const out = matchLinesFor(at(cells, 1, 1), cells, 100, 100);
          check('an interior section should have four: ' + lines(out), lines(out) === 4);
          const r = refs(out).sort().join(',');
          check('wrong neighbours referenced: ' + r, r === 'A2,B1,B3,C2');
          done();
        """)

    def test_the_building_perimeter_gets_nothing(self):
        """There is no sheet beyond the edge of the plan."""
        self.check("""
          const cells = grid(2, 2, ['0,0','1,0','0,1','1,1']);
          const out = matchLinesFor(at(cells, 0, 0), cells, 100, 100);
          check('a corner section should have two: ' + lines(out), lines(out) === 2);
          const r = refs(out).sort().join(',');
          check('wrong neighbours: ' + r, r === 'A2,B1');
          done();
        """)

    def test_an_edge_onto_an_empty_section_is_not_marked(self):
        """An empty section never gets a page, so that edge continues nowhere -
        and a match line pointing at a sheet that does not exist is worse than
        no match line."""
        self.check("""
          // B1 is empty, so A1's right-hand edge leads to no page.
          const cells = grid(2, 2, ['0,0','0,1','1,1']);
          const out = matchLinesFor(at(cells, 0, 0), cells, 100, 100);
          check('marked an edge onto an empty section: ' + refs(out),
                refs(out).join(',') === 'A2');
          check('should be exactly one line: ' + lines(out), lines(out) === 1);
          done();
        """)

    def test_a_single_section_plan_gets_none(self):
        self.check("""
          const cells = grid(1, 1, ['0,0']);
          check('marked a plan that was never split',
                matchLinesFor(at(cells, 0, 0), cells, 100, 100) === '');
          check('no cells at all should be safe',
                matchLinesFor({col:0,row:0,x0:0,y0:0,x1:1,y1:1}, null, 10, 10) === '');
          done();
        """)

    def test_it_uses_the_standard_wording(self):
        self.check("""
          const cells = grid(2, 1, ['0,0','1,0']);
          const out = matchLinesFor(at(cells, 0, 0), cells, 100, 100);
          check('not labelled as a match line: ' + out, /MATCH LINE/.test(out));
          check('does not name the continuing section: ' + out,
                /MATCH LINE \\u2014 SECTION B1/.test(out));
          done();
        """)

    def test_the_label_reads_along_a_vertical_edge(self):
        """A label lying across the line is how you make a drawing harder to
        read, not easier."""
        self.check("""
          const cells = grid(2, 1, ['0,0','1,0']);
          const out = matchLinesFor(at(cells, 0, 0), cells, 100, 100);
          check('vertical edge label was not rotated: ' + out,
                /transform="rotate\\(-90/.test(out));
          done();
        """)


class MatchLineStyling(unittest.TestCase):
    def test_it_is_dashed_and_survives_print(self):
        js = REPORT_JS.read_text(encoding="utf-8")
        css = CSS.read_text(encoding="utf-8")
        self.assertIn("stroke-dasharray", js)
        block = css[css.index(".rep-matchline {"):]
        self.assertIn("@media print", block[:1400])
        self.assertIn(".rep-matchline-label { fill:", block[:1400])


if __name__ == "__main__":
    unittest.main()
