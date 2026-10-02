"""AP Labeler: the names it writes are the ones the project and the clicks say.

Four defects, each green under the old tests because nothing ran the code that
decides a name:

* Adopting a project's own scheme turned the column that changes between
  floors into a Floor segment, which is rebuilt from the storey number. A
  project written ``F1`` / ``F2`` therefore came out ``01`` / ``02`` on every
  AP - adopting the building's own names renamed the building.
* Manual (click) numbering walked floors first, so a run clicked upstairs and
  then down was renumbered in floor order; "Next" and the undo toast counted
  clicks rather than reading the sequence.
* A counter start of 0 became 1 (``|| 1``).
* Row / column spacing was converted with the floor on screen and the image
  displayed for it, so the download depended on which tab was open.

Driven in Node against the real functions, sliced out of ap-rename.js by
counting braces. Every name and id here is invented.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AP_JS = ROOT / "web" / "assets" / "js" / "ap-rename.js"

NODE_TIMEOUT_S = 120

PRELUDE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function slice(marker) {
  const a = src.indexOf(marker);
  if (a < 0) throw new Error('slice marker moved: ' + marker);
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    if (src[b] === '{') { depth++; seen = true; }
    else if (src[b] === '}') depth--;
    b++;
  }
  return src.slice(a, b);
}
function load(markers) {
  // Indirect eval would lose the caller's stubs, so hand back the source.
  return markers.map(slice).join(';\n') + ';\n';
}
"""


def run_node(body: str) -> dict:
    program = PRELUDE + body
    r = subprocess.run(["node", "-e", program, str(AP_JS)],
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip())
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    if not lines:
        raise AssertionError("the probe printed nothing:\n" + r.stderr)
    return json.loads(lines[-1])


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class AnAdoptedSchemeReproducesTheNamesTests(unittest.TestCase):
    """Adopting the project's own scheme, with the order unchanged, must give
    every AP the name it already has."""

    PROBE = r"""
var S = { aps: [], floors: [] };
var _segments = [], _inferred = null, _nesting = 'floor', _scope = 'all';
var SEP = { value: '-', options: [{ value: '-' }, { value: '_' }, { value: '.' }, { value: ' ' }] };
var BOX = { hidden: true, innerHTML: '' };
function $(id) { return id === 'arSepStructured' ? SEP : id === 'arInferred' ? BOX : null; }
function esc(s) { return String(s); }
function renderSegments() {}
function updateAll() {}
function arSetScope(s) { _scope = s; }
eval(load([
  '  function getFloorNumber(', '  function keptPart(', '  function buildStructuredName(',
  '  function padNum(', '  function _modal(', '  function _detectSeparator(',
  '  function _asCounter(', '  function inferSegments(', '  function adoptProjectScheme(',
  '  function padSegments(', '  function renderNoSchemeNote(', '  function renderInferredNote(',
]));
var SEPARATOR_CANDIDATES = ['-', '_', '.', ' '];
var COUNTER_RE = /^(.*?)(\d+)$/;
var MIN_VISIBLE_SEGMENTS = 3;
eval(load(['  function floorTokens(', '  function tokensAreFloorNumbers(']));

S.floors = [{ id: 'fl-a', name: 'Level One', num: 1 }, { id: 'fl-b', name: 'Level Two', num: 2 }];
const tokenFor = TOKENS;
S.aps = [];
S.floors.forEach(function (f, fi) {
  for (let k = 1; k <= 3; k++) {
    S.aps.push({ id: f.id + '-' + k, floorPlanId: f.id,
                 name: 'ZED-BX-' + tokenFor[fi] + '-AP0' + k, _k: k });
  }
});
// A newly placed AP on the second floor, still carrying Ekahau's placeholder.
S.aps.push({ id: 'new-1', floorPlanId: 'fl-b', name: 'AP-9', _k: 4 });
adoptProjectScheme();
const out = {};
S.aps.forEach(function (ap) {
  const floor = S.floors.find(function (f) { return f.id === ap.floorPlanId; });
  out[ap.id] = { was: ap.name, now: buildStructuredName(floor, ap._k, ap) };
});
console.log(JSON.stringify({ names: out, types: _segments.map(function (s) { return s.type; }) }));
"""

    def _adopt(self, tokens):
        return run_node(self.PROBE.replace("TOKENS", json.dumps(tokens)))

    def test_floor_tokens_that_are_not_floor_numbers_are_kept(self):
        got = self._adopt(["F1", "F2"])
        for ap_id, row in got["names"].items():
            if ap_id == "new-1":
                continue
            self.assertEqual(row["now"], row["was"], got)

    def test_a_new_ap_takes_its_own_floors_token(self):
        got = self._adopt(["F1", "F2"])
        self.assertEqual(got["names"]["new-1"]["now"], "ZED-BX-F2-AP04", got)

    def test_tokens_that_are_the_floor_numbers_stay_a_floor_segment(self):
        got = self._adopt(["01", "02"])
        self.assertIn("floor", got["types"], got)
        for ap_id, row in got["names"].items():
            if ap_id != "new-1":
                self.assertEqual(row["now"], row["was"], got)
        self.assertEqual(got["names"]["new-1"]["now"], "ZED-BX-02-AP04", got)


MANUAL_HARNESS = r"""
var S = { floors: [{ id: 'fl-a', name: 'One' }, { id: 'fl-b', name: 'Two' }],
          aps: [
            { id: 'a', name: 'X1', floorPlanId: 'fl-a', x: 1, y: 1 },
            { id: 'b', name: 'X2', floorPlanId: 'fl-a', x: 5, y: 1 },
            { id: 'c', name: 'X3', floorPlanId: 'fl-b', x: 1, y: 1 },
            { id: 'd', name: 'X4', floorPlanId: 'fl-b', x: 5, y: 1 }],
          manualOrder: [], manualUndo: [], preview: [], byId: {}, currentFloor: 'fl-a' };
var _scope = SCOPE, _nesting = 'floor', _floorPick = 'all', _segments = [], _colorOrder = [];
var _zoom = { suppressClick: false };
var SET = { mode: 'simple', prefix: 'AP', sep: '-', digits: 3, startNum: 1, order: 'manual' };
function getSettings() { return SET; }
function isManual() { return true; }
var toasts = [];
function toast(m) { toasts.push(m); }
function updateAll() { generatePreview(); }
var window = {};
eval(load([
  '  function floorIncluded(', '  function getFloorAPs(', '  function sortAPs(',
  '  function sortManual(', '  function padNum(', '  function generateName(',
  '  function getStartNum(', '  function buildSequence(', '  function generatePreview(',
  '  function manualIndex(', '  function manualSnapshot(',
]));
eval(load(['  window.arManualClick = function', '  window.arManualUndo = function']));
eval(load(['  function manualNextNum(', '  function counterStart(']));
function nums() {
  const o = {};
  S.preview.forEach(function (it) { if (it.num != null) o[it.ap.id] = it.newName; });
  return o;
}
"""


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ManualNumberingFollowsTheClicksTests(unittest.TestCase):

    def _run(self, scope, body):
        return run_node(MANUAL_HARNESS.replace("SCOPE", json.dumps(scope)) + body)

    def test_continuous_numbers_in_click_order_across_floors(self):
        got = self._run("all", r"""
['c', 'd', 'a'].forEach(function (id) { window.arManualClick(id); });
console.log(JSON.stringify(nums()));
""")
        self.assertEqual(got, {"c": "AP-001", "d": "AP-002", "a": "AP-003"})

    def test_restart_each_floor_numbers_each_floors_clicks_from_the_start(self):
        got = self._run("perFloor", r"""
['d', 'a', 'c', 'b'].forEach(function (id) { window.arManualClick(id); });
console.log(JSON.stringify(nums()));
""")
        self.assertEqual(got, {"d": "AP-001", "c": "AP-002",
                               "a": "AP-001", "b": "AP-002"})

    def test_next_is_what_the_next_click_on_this_floor_gets(self):
        got = self._run("perFloor", r"""
['c', 'd', 'a'].forEach(function (id) { window.arManualClick(id); });
S.currentFloor = 'fl-a';
const shownA = manualNextNum();
window.arManualClick('b');
const gotB = S.byId.b.num;
S.currentFloor = 'fl-b';
console.log(JSON.stringify({ shownA: shownA, gotB: gotB, shownB: manualNextNum() }));
""")
        self.assertEqual(got["shownA"], got["gotB"])
        self.assertEqual(got, {"shownA": 2, "gotB": 2, "shownB": 3})

    def test_undo_names_the_number_that_was_released(self):
        got = self._run("perFloor", r"""
['c', 'd', 'a'].forEach(function (id) { window.arManualClick(id); });
const had = S.byId.a.num;
window.arManualUndo();
console.log(JSON.stringify({ had: had, toast: toasts[toasts.length - 1] }));
""")
        self.assertEqual(got["had"], 1)
        self.assertTrue(got["toast"].startswith("Released 1 "), got)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class ACounterMayStartAtZeroTests(unittest.TestCase):

    def test_start_zero_numbers_from_zero(self):
        got = run_node(r"""
var _segments = [{ type: 'text', value: 'ZED' },
                 { type: 'counter', tag: 'AP', start: 0, digits: 3 }];
eval(load(['  function getStartNum(', '  function counterStart(']));
console.log(JSON.stringify({ start: getStartNum({ mode: 'structured' }) }));
""")
        self.assertEqual(got["start"], 0)


@unittest.skipUnless(shutil.which("node"), "node is not installed")
class SpacingDoesNotDependOnTheOpenTabTests(unittest.TestCase):
    """Rows, left to right, with a fixed line spacing. Floor two's order is
    read with each tab open in turn; it must not change."""

    def test_every_tab_gives_floor_two_the_same_order(self):
        got = run_node(r"""
var S = { floors: [
            { id: 'fl-a', name: 'One', width: 1000, height: 1000, imageId: 'im-a' },
            { id: 'fl-b', name: 'Two', width: 1000, height: 1000, imageId: 'im-b' }],
          aps: [], imageRes: { 'im-a': { w: 4000, h: 4000 }, 'im-b': { w: 1000, h: 1000 } },
          manualOrder: [], currentFloor: 'fl-a' };
// Floor two's plan is 1000px for 1000 units, so a 100px line spacing is 100
// units: rows p q r (y under 100) then s t. Floor one's plan is drawn at four
// times the resolution, so its scale makes the same 100px 25 units; auto
// clustering, which is what an unreadable size falls back to, sees one row.
[['p', 0, 10], ['q', 300, 90], ['r', 600, 30], ['s', 100, 120], ['t', 400, 190]]
  .forEach(function (r) { S.aps.push({ id: r[0], floorPlanId: 'fl-b', x: r[1], y: r[2] }); });
S.aps.push({ id: 'u', floorPlanId: 'fl-a', x: 5, y: 5 });
var IMG = null;
var SPACING = { value: '100' };
function $(id) { return id === 'arSpacing' ? SPACING : id === 'arPlanImg' ? IMG : null; }
var _nesting = 'floor', _colorOrder = [], _scope = 'all';
eval(load([
  '  function getFloorAPs(', '  function getSpacingUnits(', '  function sortAPs(',
  '  function sortByRow(', '  function clusterByAxis(', '  function clusterByFixedSpacing(',
  '  function avg(', '  function buildSequence(',
]));
function floorTwo() {
  return buildSequence({ order: 'row-ltr' })
    .filter(function (s) { return s.floor.id === 'fl-b'; })
    .map(function (s) { return s.ap.id; }).join('');
}
const out = {};
// The displayed image is the open tab's own plan.
S.currentFloor = 'fl-b'; IMG = { naturalWidth: 1000, naturalHeight: 1000 };
out.onItsOwnTab = floorTwo();
S.currentFloor = 'fl-a'; IMG = { naturalWidth: 4000, naturalHeight: 4000 };
out.onAnotherTab = floorTwo();
S.currentFloor = '__unplaced'; IMG = { naturalWidth: 0, naturalHeight: 0 };
out.unplacedTab = floorTwo();
console.log(JSON.stringify(out));
""")
        self.assertEqual(got["onItsOwnTab"], "pqrst", got)
        self.assertEqual(got["onAnotherTab"], "pqrst", got)
        self.assertEqual(got["unplacedTab"], "pqrst", got)


if __name__ == "__main__":
    unittest.main()
