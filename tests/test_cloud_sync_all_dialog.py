"""Sync all: pick what runs, see all of it, and keep the two jobs apart.

"I saw the sync all and clicked it - the wall of text, and selected sites are
limited. Why is it designed this way? It's terrible, and explains why I have
apprehension."

He was right on every count, and the four faults compound into that sentence:

* **All or nothing on fifty-one live projects.** No per-row choice. He had been
  working one row at a time *because it felt safer*, and this offered the exact
  opposite with a single button.
* **The lists read as truncated.** Every row was rendered, but the box was
  `max-height: 220px` - about three rows of twenty-seven, with nothing saying
  the rest was below. "3 of 27" is the fair reading of what was on screen.
* **Two very different operations behind one button.** Downloading twenty-four
  projects he has no local copy of cannot lose anything. Replacing twenty-seven
  local files can. "Sync 51" made him take the second to get the first.
* **Three paragraphs of caveats**, one of which apologised for not knowing
  whether both sides had changed. That is answerable now, so the apology is
  replaced by a per-row fact.

The selection logic is driven for real rather than read, because "the button
says 4 after you untick 47" is a claim about behaviour.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
CSS = ROOT / "web" / "assets" / "wd-tools.css"
NODE_TIMEOUT_S = 120

NODE_SCRIPT = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[2], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
const block = slice('function _syncRowsHtml(rows, dir)', '\nasync function syncEverything');

function e(s) { return String(s == null ? '' : s); }
function fmtRelDate(t) { return t ? ('t' + t) : ''; }
const _compareResults = new Map();
function _compareKey(cloudId, localPath) {
  return String(cloudId || '') + '\u0000' + String(localPath || '').replace(/\\/g, '/').toLowerCase();
}
function syncEverythingPlan() { return { down: [], up: [], fresh: [], inSync: [] }; }
function _resolveConfirmAction() {}
function checkRealDifference() {}
function toast() {}

// Enough of a DOM for the selection logic: the boxes are objects and the
// selector is parsed for its data-kind, which is all the code uses.
let BOXES = [];
const okBtn = { textContent: '', disabled: false };
const heads = { 'syncAll-down': { checked: true, indeterminate: false },
                'syncAll-fresh': { checked: true, indeterminate: false } };
const document = {
  querySelectorAll(sel) {
    const m = /data-kind="([a-z]+)"/.exec(sel);
    return m ? BOXES.filter(b => b.kind === m[1]) : BOXES.slice();
  },
  getElementById(id) {
    if (id === 'confirmActionOkBtn') return okBtn;
    return heads[id] || null;
  },
};

const fn = new Function('e','fmtRelDate','_compareResults','_compareKey','syncEverythingPlan','_resolveConfirmAction','checkRealDifference','toast','document',
  block + '\nreturn { _syncPickRowsHtml, _syncVerdictCell, _syncPickUpdate, _syncPickAll, _syncPicked, _syncRowsHtml };');
const api = fn(e,fmtRelDate,_compareResults,_compareKey,syncEverythingPlan,_resolveConfirmAction,checkRealDifference,toast,document);

const out = {};

// 27 rows, like the screen he reported
const down = [];
for (let i = 0; i < 27; i++) {
  down.push({ cloudId: 'c' + i, localPath: 'C:/x/' + i + '.esx',
              cloudName: 'Project ' + i, localName: 'Project ' + i,
              cloudMtime: 200, localMtime: 100 });
}
const fresh = [];
for (let i = 0; i < 24; i++) fresh.push({ id: 'f' + i, name: 'New ' + i, siteName: 'Site' });

out.downHtml = api._syncPickRowsHtml(down, 'down', 'down-dir', true);
out.freshHtml = api._syncPickRowsHtml(fresh, 'fresh', 'fresh-dir', false);
out.downRowCount = (out.downHtml.match(/<tr>/g) || []).length;
out.freshRowCount = (out.freshHtml.match(/<tr>/g) || []).length;

// verdicts
out.verdictUnchecked = api._syncVerdictCell(down[0]);
_compareResults.set(_compareKey('c0', 'C:/x/0.esx'),
  { designDiffers: false, renamedOnly: true, summary: 'Renamed only' });
out.verdictNameOnly = api._syncVerdictCell(down[0]);
_compareResults.set(_compareKey('c1', 'C:/x/1.esx'),
  { designDiffers: true, renamedOnly: false, summary: 'Real changes: accessPoints (3 changed)' });
out.verdictDiffers = api._syncVerdictCell(down[1]);

// selection behaviour
BOXES = [];
for (let i = 0; i < 27; i++) BOXES.push({ kind: 'down', checked: true, getAttribute: () => String(i) });
for (let i = 0; i < 24; i++) BOXES.push({ kind: 'fresh', checked: true, getAttribute: () => String(i) });
api._syncPickUpdate();
out.buttonAllOn = okBtn.textContent;

BOXES.filter(b => b.kind === 'down').forEach((b, i) => { if (i >= 4) b.checked = false; });
api._syncPickUpdate();
out.buttonAfterUnticking = okBtn.textContent;
out.downHeadIndeterminate = heads['syncAll-down'].indeterminate;
out.freshHeadChecked = heads['syncAll-fresh'].checked;

api._syncPickAll('fresh', false);
out.buttonAfterDroppingFresh = okBtn.textContent;
out.pickedDownCount = api._syncPicked('down').length;
out.pickedFreshCount = api._syncPicked('fresh').length;

BOXES.forEach(b => { b.checked = false; });
api._syncPickUpdate();
out.buttonNoneSelected = okBtn.textContent;
out.buttonDisabledWhenNone = okBtn.disabled;

process.stdout.write(JSON.stringify(out));
process.exit(0);
"""


_PROBE = {}


def probe():
    """Run the dialog's own code once and cache it.

    Both classes read the same run. Hanging it off one class and reaching for
    it from the other depends on unittest's alphabetical class ordering, which
    happens to work here and did not in `test_cloud_push_to_replace.py` earlier
    today - the reader ran first and found no attribute.
    """
    if not _PROBE:
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "probe.js"
            script.write_text(NODE_SCRIPT, encoding="utf-8")
            proc = subprocess.run(["node", str(script), str(CLOUD_JS)],
                                  capture_output=True, timeout=NODE_TIMEOUT_S)
        if proc.returncode != 0:
            raise AssertionError(
                "node failed: " + proc.stderr.decode("utf-8", "replace"))
        _PROBE.update(json.loads(proc.stdout.decode("utf-8", "replace")))
    return _PROBE


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class HeCanChooseWhatRunsTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = probe()

    def test_every_row_is_rendered_not_a_sample(self):
        """He saw three of twenty-seven. All twenty-seven are listed."""
        self.assertEqual(27, self.out["downRowCount"])
        self.assertEqual(24, self.out["freshRowCount"])

    def test_every_row_has_its_own_checkbox(self):
        self.assertEqual(27, self.out["downHtml"].count('class="sync-pick"'))
        self.assertEqual(24, self.out["freshHtml"].count('class="sync-pick"'))

    def test_the_button_counts_what_is_actually_ticked(self):
        """"Sync 51" while he has unticked forty-seven of them would be the
        same kind of untrue label the rest of this screen is being fixed for."""
        self.assertEqual("Sync 51", self.out["buttonAllOn"])
        self.assertEqual("Sync 28", self.out["buttonAfterUnticking"])

    def test_the_two_operations_are_selectable_apart(self):
        """Downloading projects he has no copy of is harmless; replacing local
        files is not. Turning one off must not touch the other."""
        self.assertTrue(self.out["freshHeadChecked"])
        self.assertEqual("Sync 4", self.out["buttonAfterDroppingFresh"])
        self.assertEqual(4, self.out["pickedDownCount"])
        self.assertEqual(0, self.out["pickedFreshCount"])

    def test_a_partly_ticked_section_shows_as_partial(self):
        self.assertTrue(self.out["downHeadIndeterminate"])

    def test_it_will_not_offer_to_sync_nothing(self):
        self.assertEqual("Nothing selected", self.out["buttonNoneSelected"])
        self.assertTrue(self.out["buttonDisabledWhenNone"])


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class TheRowSaysWhatActuallyDiffersTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = probe()

    def test_an_unchecked_row_says_so_rather_than_implying_it_is_fine(self):
        self.assertIn("not checked", self.out["verdictUnchecked"])

    def test_a_rename_only_row_is_marked_safe(self):
        """The row he can tick without thinking - and after a bulk rename,
        most of them."""
        self.assertIn("cmp-same", self.out["verdictNameOnly"])
        self.assertIn("name only", self.out["verdictNameOnly"])

    def test_a_row_with_real_changes_says_what_they_are(self):
        self.assertIn("cmp-differs", self.out["verdictDiffers"])
        self.assertIn("accessPoints (3 changed)", self.out["verdictDiffers"])


class TheListIsNotVisuallyTruncatedTests(unittest.TestCase):

    def test_the_scroll_box_is_not_three_rows_tall(self):
        """`max-height: 220px` rendered every row and showed about three, which
        is why a complete list was reported as a truncated one."""
        css = CSS.read_text(encoding="utf-8")
        m = re.search(r"\.sync-plan-wrap \{ max-height: ([^;]+);", css)
        self.assertIsNotNone(m, "the plan box lost its max-height rule")
        self.assertNotIn("220px", m.group(1))
        self.assertIn("vh", m.group(1),
                      "size it against the viewport, not a fixed three rows")

    def test_each_section_says_how_many_it_is_listing(self):
        js = CLOUD_JS.read_text(encoding="utf-8")
        self.assertIn("listed above", js)
        self.assertIn("scroll the", js)


if __name__ == "__main__":
    unittest.main()
