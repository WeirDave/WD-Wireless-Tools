"""Prep shows a CAD plan on white paper, and puts back a page an old crop lost.

Two halves of one symptom: a vector floor plan showing as grey lines on black.

* Prep's own plan view drew the image straight onto the dark stage, so any
  transparent part of a CAD plan read as black. PlanTrim's canvas was given a
  white page under the plan in suite 2.190.0; Prep's view was not. (That half
  is now held by tests/test_plan_view.py, since Prep draws on the shared
  canvas.)
* Suite 2.190.0 also taught the trimmer to repair a plan an earlier crop had
  left without its page. Prep's pipeline kept the trim's output only when a
  floor was *cut*, so a repair with nothing to cut was thrown away - and a
  floor trimmed earlier has nothing left to cut, which is exactly the floor
  that needs the repair.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from tools import esx_trimmer, prep_pipeline

from tests.test_plantrim_svg_background import (
    DRAWING, IMG_A, LEFT_BY_AN_EARLIER_TRIM, _project)
from tests.test_prep_shows_the_crop_on_the_plan import needs_node, node


class ThePipelineKeepsARepairWithNothingToCut(unittest.TestCase):

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = Path(self._tmp.name)
        self.src = _project(self.tmp / "Old.esx", LEFT_BY_AN_EARLIER_TRIM, 400, 300)

    def test_the_preview_reports_the_repair(self):
        out = prep_pipeline.plan(self.src, steps=["trim"])
        trim = out["step"]["trim"]
        self.assertEqual(trim["trimmedCount"], 0)
        self.assertEqual(trim["repairedCount"], 1)
        self.assertTrue(trim["floors"][0]["repaired"])

    def test_preparing_writes_the_repaired_page(self):
        dest = self.tmp / "Old (prepared).esx"
        res = prep_pipeline.run(self.src, dest=dest, steps=["trim"])
        self.assertTrue(res["written"], res)
        with zipfile.ZipFile(dest) as z:
            img = z.read("image-" + IMG_A)
        self.assertIn(b'<rect width="950" height="700" fill="white"/>', img)
        self.assertTrue(img.endswith(DRAWING + b"</svg>"))
        self.assertEqual(res["step"]["trim"]["repairedCount"], 1)

    def test_a_plan_with_nothing_to_cut_or_repair_is_still_left_alone(self):
        once = self.tmp / "Once.esx"
        esx_trimmer.trim(self.src, once)
        res = prep_pipeline.run(once, dest=self.tmp / "Twice.esx", steps=["trim"])
        self.assertFalse(res["written"], res)


PREVIEW_HARNESS = r"""
const els = {};
function mk(id) { return els[id] || (els[id] = { id, hidden: false, disabled: false,
  innerHTML: '', textContent: '', checked: false, children: [], classList: { toggle() {} } }); }
function $(id) { return mk(id); }
function esc(s) { return String(s == null ? '' : s).replace(/&/g,'&amp;').replace(/</g,'&lt;'); }
function escAttr(s) { return esc(s).replace(/"/g,'&quot;'); }
function plural(n, one, many) { return n === 1 ? one : (many || one + 's'); }
function clearanceLine() { return ''; }
function syncSavedBoxes() {}
function renderMap() {}
eval(fn('function stepCard(title, badge, badgeCls, lines) {'));
eval(fn('function setGo(on, note) {'));
eval(fn('function renderPreview(r) {'));
"""


@needs_node
class ThePageOffersTheRepair(unittest.TestCase):

    def test_a_repair_alone_enables_prepare(self):
        out = node(PREVIEW_HARNESS + r"""
renderPreview({ ok: true, steps: ['trim'], step: { trim: {
  trimmedCount: 0, repairedCount: 1, floorCount: 1,
  floors: [{ id: 'f1', name: 'Ground', action: 'skipped',
             reason: 'content already fills 100% of the canvas', repaired: true }] } } });
console.log(JSON.stringify({ off: mk('prepGoBtn').disabled,
                             html: mk('prepPreview').innerHTML }));
""")
        self.assertFalse(out["off"], "Prepare stays disabled with a repair to write")
        self.assertIn("1 to repair", out["html"])
        self.assertIn("white page", out["html"])

    def test_nothing_to_cut_and_nothing_to_repair_still_offers_nothing(self):
        out = node(PREVIEW_HARNESS + r"""
renderPreview({ ok: true, steps: ['trim'], step: { trim: {
  trimmedCount: 0, repairedCount: 0, floorCount: 1,
  floors: [{ id: 'f1', name: 'Ground', action: 'skipped', reason: 'tight' }] } } });
console.log(JSON.stringify({ off: mk('prepGoBtn').disabled }));
""")
        self.assertTrue(out["off"])

    def test_the_summary_says_what_was_repaired(self):
        out = node(r"""
function plural(n, one, many) { return n === 1 ? one : (many || one + 's'); }
eval(fn('function didWhat(r) {'));
eval(fn('function summaryOf(r) {'));
console.log(JSON.stringify([
  summaryOf({ ran: ['trim'], failed: [], step: { trim: { trimmedCount: 0, repairedCount: 2, floorCount: 3 } } }),
  didWhat({ ran: ['trim'], failed: [], trimmed: 1, repaired: 1, floorCount: 2 }),
]));
""")
        self.assertIn("white page back behind <b>2</b> floor plans", out[0])
        self.assertIn("behind <b>1</b> floor plan ", out[1])


# The white page under the plan moved into the shared canvas Prep now draws
# on, WD.PlanView; tests/test_plan_view.py holds it, in Node and in Chrome,
# Edge and Firefox.


if __name__ == "__main__":
    unittest.main()
