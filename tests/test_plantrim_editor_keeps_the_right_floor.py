"""PlanTrim's box editor keeps each answer with the floor and file it is for.

Three ways the page let one thing's answer land on another:

* **Suggest from the set** filled every floor it had a suggestion for, cropped
  ones included. A cropped floor's box is what ``persist()`` stores, so a
  suggestion nobody had checked replaced his crop in the store and went to the
  server on the next analyze.
* **Next floor pressed twice**: a large plan for the floor already left behind
  could finish decoding after the next floor's, and became the picture under
  the selected floor - a box drawn on it was saved against the wrong floor.
* **A second file opened while the first was being read**: both readings were
  in flight, and whichever answered last became the report, so the second file
  could be described by the first file's floors.

Each runs the real function, sliced out of ``plantrim.js`` by counting braces,
in Node against recording stubs.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLANTRIM_JS = ROOT / "web" / "assets" / "js" / "plantrim.js"

SLICE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function fn(head) {
  const a = src.indexOf(head);
  if (a < 0) throw new Error(head + ' moved');
  let b = a, depth = 0, seen = false;
  while (b < src.length && !(seen && depth === 0)) {
    if (src[b] === '{') { depth++; seen = true; }
    else if (src[b] === '}') depth--;
    b++;
  }
  return src.slice(a, b);
}
const tick = () => new Promise(r => setTimeout(r, 5));
"""

SUGGEST = SLICE + r"""
const made = {};
function $(id) { return made[id] || (made[id] = { hidden: false, disabled: false, textContent: '' }); }
const window = {};
const toasts = [];
const WD = { toast: (m, k) => toasts.push([m, k]), esc: String };
const box = { boxes: { f1: [100, 100, 900, 700] }, applied: { f1: true }, current: 'f1' };
function draw() {} function updateReadout() {} function showEvidence() {} function reanalyze() {}
window.__ptSuggest = () => Promise.resolve({ ok: true, suggestions: [
  { floorId: 'f1', box: [0, 0, 400, 300], basis: 'single-sheet', evidence: 'x' },
  { floorId: 'f2', box: [10, 20, 410, 320], basis: 'cross-sheet', sheets: 2, evidence: 'y' }] });
eval(fn('  window.ptbSuggest = function'));
eval(fn('  window.__ptBoxes = function'));
(async () => {
  window.ptbSuggest();
  await tick(); await tick();
  console.log(JSON.stringify({ boxes: box.boxes, sent: window.__ptBoxes(),
                               suggestedFor: Object.keys(box.suggestions), toasts }));
})().catch(e => { console.error(e); process.exit(1); });
"""

FLOOR_RACE = SLICE + r"""
const made = {};
function $(id) { return made[id] || (made[id] = { hidden: false, textContent: '' }); }
const window = {};
const WD = { imageMime: () => 'image/png' };
const URL = { createObjectURL: () => 'blob:x', revokeObjectURL() {} };
global.Blob = function () {};
const pending = [];
global.Image = function () { pending.push(this); };
const zip = { file: (name) => ({ async: () => Promise.resolve(name) }) };
const box = { zip, boxes: {}, applied: {}, current: null, img: null,
  floors: [{ id: 'f1', imageId: 'big', w: 9000, h: 6000 },
           { id: 'f2', imageId: 'small', w: 3000, h: 2000 }] };
function floorById(id) { return box.floors.find(f => f.id === id) || null; }
const laidOut = [];
function sizeCanvas() {} function draw() {} function updateReadout() {}
function showEvidence() {} function renderStrip() {}
function fitView() { laidOut.push(box.current + ':' + (box.img && box.img.width)); }
eval(fn('  function loadImage(f)'));
eval(fn('  window.ptbSelectFloor = function'));
(async () => {
  window.ptbSelectFloor('f1');
  await tick();
  window.ptbSelectFloor('f2');
  await tick();
  if (pending.length !== 2) throw new Error('expected two images, got ' + pending.length);
  const [big, small] = pending;
  small.width = 3000; small.height = 2000; small.onload();
  await tick();
  big.width = 9000; big.height = 6000; big.onload();
  await tick();
  console.log(JSON.stringify({ current: box.current, imgFor: box.imgFor,
                               width: box.img && box.img.width, laidOut }));
})().catch(e => { console.error(e); process.exit(1); });
"""

ANALYZE_RACE = SLICE + r"""
const made = {};
function $(id) { return made[id] || (made[id] = { hidden: false, innerHTML: '', textContent: '' }); }
const window = {}; const esc = String;
var state = { file: { name: 'first.esx' }, bytes: 'FIRST', report: null, busy: false };
const calls = [];
function postEsx(action, bytes) { return new Promise(r => calls.push({ bytes, r })); }
function analyzeParams() { return {}; }
function busy(on) { state.busy = on; }
function syncCutButton() {}
eval(fn('  function analyze()'));
(async () => {
  analyze();
  state.bytes = 'SECOND'; state.file = { name: 'second.esx' }; state.report = null;
  analyze();
  await tick();
  if (calls.length !== 2) throw new Error('expected two readings, got ' + calls.length);
  calls[1].r({ json: () => ({ ok: true, file: 'second' }) }); await tick();
  calls[0].r({ json: () => ({ ok: true, file: 'first' }) }); await tick();
  console.log(JSON.stringify({ reportFor: state.report && state.report.file,
                               busy: state.busy }));
})().catch(e => { console.error(e); process.exit(1); });
"""


def run(probe):
    r = subprocess.run(["node", "-e", probe, str(PLANTRIM_JS)],
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip())
    return json.loads(r.stdout.strip().splitlines()[-1])


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class SuggestLeavesACroppedFloorAlone(unittest.TestCase):
    def test_the_crop_is_what_is_sent_and_the_toast_says_so(self):
        out = run(SUGGEST)
        self.assertEqual(out["boxes"]["f1"], [100, 100, 900, 700],
                         "the suggestion replaced a floor he had cropped")
        self.assertEqual(out["sent"], {"f1": [100, 100, 900, 700]})
        # The undecided floor still gets its suggestion.
        self.assertEqual(out["boxes"]["f2"], [10, 20, 410, 320])
        self.assertEqual(out["suggestedFor"], ["f2"])
        message = out["toasts"][-1][0]
        self.assertRegex(message, r"\b1 floor\b")
        self.assertRegex(message, r"left 1 cropped floor")


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheSelectedFloorShowsItsOwnPlan(unittest.TestCase):
    def test_a_slow_earlier_plan_does_not_replace_the_selected_one(self):
        out = run(FLOOR_RACE)
        self.assertEqual(out["current"], "f2")
        self.assertEqual(out["imgFor"], "small", out)
        self.assertEqual(out["width"], 3000, out)
        # Laid out once, for the floor selected, with its own image.
        self.assertEqual(out["laidOut"], ["f2:3000"])


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheReportDescribesTheFileOpen(unittest.TestCase):
    def test_the_first_files_late_answer_is_ignored(self):
        out = run(ANALYZE_RACE)
        self.assertEqual(out["reportFor"], "second", out)
        self.assertFalse(out["busy"])


if __name__ == "__main__":
    unittest.main()
