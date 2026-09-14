"""The floor strip must never hide that a box was drawn.

`floorState()` was given the trim report and nothing else, so it reported the
outcome and concealed the input: a floor the user had drawn a box on could read
**Automatic**, the page crediting the machine for a decision he had made
himself. That is the one state where the strip was actively misleading rather
than merely terse.

The rule these hold: whatever the trim did, if a box exists for that floor the
row says so — and a box that was not used says it was not used, rather than
going quiet.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLANTRIM_JS = ROOT / "web" / "assets" / "js" / "plantrim.js"
NODE_TIMEOUT_S = 120

PRELUDE = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('  function floorState(rep, id)');
const b = src.indexOf('  // Ekahau lets the customer name a floor');
if (a < 0 || b < 0) throw new Error('the floor-strip block moved');
var box = { boxes: {}, floors: [] };
eval(src.slice(a, b));

// The two outcomes a floor can reach, with and without a drawn box.
const REP = { floors: [
  { id: 'auto',    action: 'trimmed', source: 'auto',   oldSize: [100, 100],
    newSize: [50, 50], areaSavedPct: 75 },
  { id: 'manual',  action: 'trimmed', source: 'manual', oldSize: [100, 100],
    newSize: [60, 60], areaSavedPct: 64 },
  { id: 'skipped', action: 'skipped', reason: 'content already fills the canvas' },
  { id: 'refused', action: 'refused', reason: '3 access points would be stranded' },
] };
function state(id, drawn) {
  box.boxes = drawn ? { [id]: [1, 2, 3, 4] } : {};
  return floorState(REP, id);
}
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class FloorStripDisclosesADrawnBox(unittest.TestCase):
    def run_node(self, script):
        proc = subprocess.run(["node", "-e", PRELUDE + script, str(PLANTRIM_JS)],
                              capture_output=True, text=True, encoding="utf-8",
                              timeout=NODE_TIMEOUT_S)
        if proc.returncode != 0:
            raise AssertionError("node failed:\n" + proc.stderr)
        return json.loads(proc.stdout)

    def test_an_automatic_crop_with_a_drawn_box_says_the_box_was_not_used(self):
        """The reported bug: the page credited the machine for his decision."""
        out = self.run_node(
            "console.log(JSON.stringify(state('auto', true)));")
        self.assertEqual(out["word"], "Automatic")
        self.assertIn("your box was not used", out["detail"])

    def test_an_automatic_crop_with_no_box_is_unchanged(self):
        """The common case must not gain noise about a box that never existed."""
        out = self.run_node(
            "console.log(JSON.stringify(state('auto', false)));")
        self.assertEqual(out["word"], "Automatic")
        self.assertNotIn("box", out["detail"])

    def test_a_manual_crop_still_reads_as_his(self):
        out = self.run_node(
            "console.log(JSON.stringify(state('manual', true)));")
        self.assertEqual(out["word"], "Your box")

    def test_a_skipped_floor_still_says_the_box_is_kept(self):
        """Nothing happened, so it matters that the drawing was not discarded."""
        out = self.run_node(
            "console.log(JSON.stringify(state('skipped', true)));")
        self.assertEqual(out["word"], "Nothing to do")
        self.assertIn("still saved", out["detail"])
        self.assertIn("fills the canvas", out["detail"])

    def test_a_refused_floor_keeps_its_reason_and_says_the_box_is_kept(self):
        out = self.run_node(
            "console.log(JSON.stringify(state('refused', true)));")
        self.assertEqual(out["word"], "Cannot crop")
        self.assertIn("stranded", out["detail"])
        self.assertIn("still saved", out["detail"])

    def test_a_skipped_floor_with_no_box_keeps_only_its_reason(self):
        out = self.run_node(
            "console.log(JSON.stringify(state('skipped', false)));")
        self.assertEqual(out["detail"], "content already fills the canvas")

    def test_a_box_drawn_before_any_crop_is_acknowledged(self):
        """Drawn and not yet cropped is not the same as nothing happening."""
        out = self.run_node(
            "box.boxes = { later: [1, 2, 3, 4] };"
            "console.log(JSON.stringify(floorState(REP, 'later')));")
        self.assertEqual(out["word"], "Your box")
        self.assertIn("not cropped yet", out["detail"])

    def test_a_floor_with_neither_report_nor_box_is_still_pending(self):
        out = self.run_node(
            "box.boxes = {};"
            "console.log(JSON.stringify(floorState(REP, 'unknown')));")
        self.assertEqual(out["cls"], "is-pending")

    def test_a_malformed_box_is_not_treated_as_drawn(self):
        """Guards the store: a truncated entry must not claim he drew one."""
        out = self.run_node(
            "box.boxes = { auto: [1, 2] };"
            "console.log(JSON.stringify(floorState(REP, 'auto')));")
        self.assertNotIn("box", out["detail"])


if __name__ == "__main__":
    unittest.main()
