"""A Crop pressed while PlanTrim is still reading the project is not lost.

The first reading of a large project takes seconds. A box drawn and cropped in
that time asked for a new reading while the page was busy, and the request
was dropped: the box was cropped and saved, and the floor went on saying
"Automatic · your box was not used", and the footer "cropped automatically",
until something else happened to ask again. Found driving the page in a
browser, where the first reading was still in flight when Crop was pressed.

Run on the real `__ptAnalyze` and `analyze`, against a server stub whose
replies the test releases by hand.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PLANTRIM_JS = ROOT / "web" / "assets" / "js" / "plantrim.js"

HARNESS = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function slice(a, b) {
  const i = src.indexOf(a), j = src.indexOf(b, i);
  if (i < 0 || j < 0) throw new Error('moved: ' + a);
  return src.slice(i, j);
}
const made = {};
function $(id) { return made[id] || (made[id] = { innerHTML: '', textContent: '', hidden: false }); }
function esc(s) { return String(s); }
const window = {};
const state = { file: { name: 'invented.esx' }, bytes: new Uint8Array(4), report: null, busy: false };
function busy(on) { state.busy = on; }
let cropped = null;                       // what __ptBoxes would answer
function analyzeParams() { return cropped ? { boxes: JSON.stringify(cropped) } : {}; }
const sent = [], replies = [];
function postEsx(action, bytes, params) {
  sent.push(params.boxes || null);
  return new Promise(r => replies.push(r));
}
function reply(rep) { replies.shift()({ json: () => rep }); }
const strips = [];
function syncCutButton() {}
window.__ptRenderStrip = rep => strips.push(rep.tag);

eval(slice('  window.__ptAnalyze = function', '  // The set comparison needs'));
eval(slice('  function analyze()', '  // The verb, next to the thing it acts on.'));
const tick = () => new Promise(r => setTimeout(r, 0));

(async () => {
  window.__ptAnalyze();                   // the first reading goes out
  cropped = { f1: [10, 20, 300, 400] };   // Crop pressed while it is in flight
  window.__ptAnalyze();
  const whileBusy = sent.length;
  reply({ ok: true, tag: 'first' });
  for (let i = 0; i < 5; i++) await tick();
  const afterFirst = sent.slice();
  if (replies.length) reply({ ok: true, tag: 'second' });
  for (let i = 0; i < 5; i++) await tick();
  console.log(JSON.stringify({ whileBusy, afterFirst, strips, busy: state.busy }));
})().catch(e => { console.error(e.stack); process.exit(1); });
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ACropDuringTheFirstReadingIsKept(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", HARNESS, str(PLANTRIM_JS)],
                           capture_output=True, encoding="utf-8", timeout=60)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        cls.out = json.loads(r.stdout.strip().splitlines()[-1])

    def test_one_reading_at_a_time(self):
        self.assertEqual(self.out["whileBusy"], 1,
                         "a second request must wait for the first, not overlap it")

    def test_the_queued_reading_goes_out_with_the_cropped_box(self):
        self.assertEqual(len(self.out["afterFirst"]), 2,
                         "the request made while busy was dropped")
        self.assertEqual(json.loads(self.out["afterFirst"][1]),
                         {"f1": [10, 20, 300, 400]})

    def test_the_floors_end_on_the_reading_that_knows_the_box(self):
        self.assertEqual(self.out["strips"], ["first", "second"])
        self.assertFalse(self.out["busy"])


if __name__ == "__main__":
    unittest.main()
