"""The AP Placement Map names its floor once.

A floor big enough to be split into sections printed its heading twice in a
row: the page head ("Floor 0", with the plan name and AP count beside it),
then the segment notice, then the section index opening with "Floor 0" again.
The index carries its own heading because other reports use it without one of
their own; on the placement map the page head is directly above it.

These run the real page renderer, the real overview and the real section
index, cut out of report.js, and count the headings in what comes back.
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

NODE_PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');

function sliceFn(marker) {
  const a = source.indexOf(marker);
  if (a < 0) throw new Error('moved: ' + marker);
  let b = a, depth = 0, seen = false;
  while (b < source.length && !(seen && depth === 0)) {
    if (source[b] === '{') { depth++; seen = true; }
    else if (source[b] === '}') depth--;
    b++;
  }
  return source.slice(a, b);
}
function sliceBetween(from, to) {
  const a = source.indexOf(from), b = source.indexOf(to);
  if (a < 0 || b < 0 || b <= a) throw new Error('moved: ' + from);
  return source.slice(a, b);
}

const WD = {
  esc: s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                     .replace(/>/g, '&gt;').replace(/"/g, '&quot;'),
  escAttr: s => String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;')
                         .replace(/'/g, '&#39;').replace(/</g, '&lt;')
                         .replace(/>/g, '&gt;'),
};
function floorPlanImageUrl() { return 'plan.png'; }
function floorNumberFor(fp) { return fp.number; }
function antennaKeyHtml() { return '<!--key-->'; }
function placementKeyHtml() { return '<!--key-->'; }
function orientPickerHtml(key) { return '<!--orient:' + key + '-->'; }
function renderReportFooter() { return '<footer></footer>'; }
function buildAntennaMarkers() { return ''; }
function renderAntennaSegmentCell(url, W, H, cell) {
  return '<!--cell:' + cell.col + ',' + cell.row + '-->';
}
// Forced to a 3x2 split so the segmented path is the one under test.
function computeAntennaGrid() { return { cols: 3, rows: 2 }; }

eval(sliceBetween('  function segCellLabel(col, row) {', '  /* The Key Plan.'));
eval(sliceFn('  function renderAntennaOverview(fp, aps, opts, ctx, keyHtml'));
eval(sliceFn('  function renderPlacementFloorSection(fp, aps, opts, ctx, floorIdx) {'));

// Invented floor: numbered 0, named "Ground", APs spread over every section.
const FLOOR = { id: 'f1', name: 'Ground', number: 0, width: 600, height: 400 };
const APS = [];
for (let i = 0; i < 12; i++) {
  APS.push({ name: 'AP-' + (i + 1),
             location: { coord: { x: 50 + (i % 6) * 100, y: i < 6 ? 100 : 300 } } });
}
function occurrences(html, needle) { return html.split(needle).length - 1; }

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
"""


def run_node(checks: str) -> subprocess.CompletedProcess:
    program = NODE_PRELUDE + "eval(" + json.dumps(checks) + ");"
    try:
        return subprocess.run(["node", "-e", program, str(REPORT_JS)],
                              capture_output=True, text=True,
                              encoding="utf-8", timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"node did not finish within {NODE_TIMEOUT_S}s") from exc


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class PlacementFloorHeadingOnce(unittest.TestCase):
    def run_block(self, checks: str):
        r = run_node(checks)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())

    def test_a_split_floor_is_headed_once(self):
        self.run_block(r"""
        const html = renderPlacementFloorSection(FLOOR, APS, { segmented: true }, {}, 0);
        check('the plan was split, so the section index is on the page',
              html.includes('rep-seg-index'));
        check('the page head names the floor',
              html.includes('rep-placement-head">Floor 0<'));
        check('"Floor 0" is a heading exactly once, not twice: found '
              + occurrences(html, 'rep-seg-floor'),
              occurrences(html, 'rep-seg-floor') === 1);
        check('the section index carries no floor heading of its own',
              !/rep-seg-index">\s*<div class="rep-seg-floor"/.test(html));
        done();
        """)

    def test_the_index_still_names_its_floor_where_nothing_else_does(self):
        """Other reports put the index under a plan-name heading of their own,
        so the index keeps its floor heading when it is not told otherwise."""
        self.run_block(r"""
        const html = renderAntennaOverview(FLOOR, APS, { segmented: true }, {});
        check('the section index names its floor',
              html.includes('<div class="rep-seg-floor">Floor 0</div>'));
        done();
        """)


if __name__ == "__main__":
    unittest.main()
