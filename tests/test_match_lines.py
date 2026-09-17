"""Match lines at section edges.

The companion to the Key Plan, and the standard AEC pair: the key plan answers
"where am I in the building", the match line answers "where does this drawing
continue" at the edge where the reader runs out of paper. Standard name, dashed
along the shared edge, labelled with the section that carries on - which is how
a run of racking is followed from sheet to sheet.

Two rules matter. Which edges get one: a section with no APs is never given a
page, so an edge onto an empty section leads nowhere, and marking it would
promise a sheet that does not exist. The building perimeter gets nothing for
the same reason.

And where the words go. They used to be SVG text inside the plan, sized
`min(cellW, cellH) * 0.045` - source-image pixels mapped onto the sheet, so
about 24pt on a Letter section - placed just inside the edge it marked. On the
bottom edge that runs straight through the AP markers and their labels, and an
installer could not read the identifiers underneath it, which is the one thing
the sheet exists for. The dashed line is part of the drawing and stays on it.
The words are not, and live in the gutter outside the image.
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
const refs = (out) => (out.labels.match(/SECTION ([A-Z]\d+)/g) || []).map(s => s.replace('SECTION ', ''));
const lines = (out) => (out.svg.match(/class="rep-matchline"/g) || []).length;
const sides = (out) => (out.labels.match(/is-(top|bottom|left|right)/g) || []).sort().join(',');

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
          const one = matchLinesFor(at(cells, 0, 0), cells, 100, 100);
          check('marked a plan that was never split', one.svg === '' && one.labels === '');
          const none = matchLinesFor({col:0,row:0,x0:0,y0:0,x1:1,y1:1}, null, 10, 10);
          check('no cells at all should be safe', none.svg === '' && none.labels === '');
          done();
        """)

    def test_it_uses_the_standard_wording(self):
        self.check("""
          const cells = grid(2, 1, ['0,0','1,0']);
          const out = matchLinesFor(at(cells, 0, 0), cells, 100, 100);
          check('not labelled as a match line: ' + out.labels, /MATCH LINE/.test(out.labels));
          check('does not name the continuing section: ' + out.labels,
                /MATCH LINE \\u2014 SECTION B1/.test(out.labels));
          done();
        """)

    def test_nothing_but_the_cut_is_drawn_on_the_drawing(self):
        """The regression this guards: words painted over the plan. The label
        is markup outside the image now, so the SVG that sits over the plan
        must carry the dashed line and nothing else."""
        self.check("""
          const cells = grid(3, 3, ['0,0','1,0','2,0','0,1','1,1','2,1','0,2','1,2','2,2']);
          const out = matchLinesFor(at(cells, 1, 1), cells, 100, 100);
          check('the overlay drawn on the plan carries text: ' + out.svg,
                out.svg.indexOf('<text') === -1);
          check('the overlay drawn on the plan carries words: ' + out.svg,
                out.svg.indexOf('MATCH LINE') === -1);
          check('a label is missing its edge: ' + sides(out),
                sides(out) === 'is-bottom,is-left,is-right,is-top');
          check('a label was sized in plan units again: ' + out.labels,
                out.labels.indexOf('font-size') === -1);
          done();
        """)


class MatchLineStyling(unittest.TestCase):
    def test_it_is_dashed_and_survives_print(self):
        js = REPORT_JS.read_text(encoding="utf-8")
        css = CSS.read_text(encoding="utf-8")
        self.assertIn("stroke-dasharray", js)
        block = css[css.index(".rep-matchline {"):]
        self.assertIn("@media print", block[:2600])

    def test_the_label_has_an_absolute_size_and_a_gutter_to_sit_in(self):
        """A size in points rather than a fraction of the plan, or it is 24pt
        again the next time somebody prints a large sheet. And a gutter, or
        "outside the image" is a claim about markup rather than about pixels."""
        css = CSS.read_text(encoding="utf-8")
        edge = css[css.index(".rep-matchline-edge {"):]
        self.assertRegex(edge[:400], r"font-size:\s*\d+(\.\d+)?pt")
        for side in ("is-top", "is-bottom", "is-left", "is-right"):
            self.assertIn(".rep-matchline-edge." + side, css)
        self.assertIn(".rep-seg-plan-wrap", css)


if __name__ == "__main__":
    unittest.main()
