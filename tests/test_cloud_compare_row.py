"""The measured answer appears in the row, beside the inferred one.

A content comparison that only wrote to a log would not fix anything: the
problem is that he reads a row saying "Cloud newer" and cannot tell whether
that means anything. So once he has asked, the answer has to be *in the row*,
outranking the timestamp guess, without hovering.

Driven through the real `stalenessBadgeHtml`, because what he reads is the
rendered row and asserting on the source would pass while the screen said
something else.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
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
// A row's controls are built from the shared icon helpers, and those sit
// above the badges. Slicing from the badges alone compiles and then throws
// `ic is not defined` on the first render - so the slice starts higher
// rather than the helper being stubbed, because a stub would test the stub.
const block = slice('const ICONS = {', '\nfunction siteDigest(')
            + slice('const MATCH_BADGE_SPEC = {', '\nfunction gutCell(r)');

const WD = { esc: s => String(s == null ? '' : s),
             escAttr: s => String(s == null ? '' : s),
             escJsStr: s => String(s == null ? '' : s) };
function e(s) { return WD.esc(s); }
function a(s) { return WD.escAttr(s); }
function j(s) { return WD.escJsStr(s); }
function pj(s) { return j(String(s == null ? '' : s).replace(/\\/g, '/')); }
let currentTab = 'projects';
function opEnqueue() { return { id: 'op', promise: Promise.resolve() }; }
function toast() {}
async function pyApi() { return {}; }
function _clearStaleness() {}
function _scheduleOpRefresh() {}
function selectedSyncItems() { return []; }
function clearSelection() {}

const fn = new Function('WD','e','a','j','pj','currentTab','opEnqueue','toast','pyApi','_clearStaleness','_scheduleOpRefresh','selectedSyncItems','clearSelection',
  block + '\nreturn { stalenessBadgeHtml, rowDetailHtml, _compareResults, _compareKey };');
const api = fn(WD,e,a,j,pj,currentTab,opEnqueue,toast,pyApi,_clearStaleness,_scheduleOpRefresh,selectedSyncItems,clearSelection);

const row = (over) => Object.assign({
  kind: 'projects', matchType: 'id', staleness: 'cloud_newer',
  differenceKind: 'renamed',
  cloud: { id: 'c1', name: 'SITE1 New', mtime: 200 },
  local: { path: 'C:/x/a.esx', name: 'SITE1 Old', mtime: 100 },
}, over || {});

const out = {};
// The verdict and the check live in the full-width detail row now, not in the
// gutter between the two name columns - that lane is a few characters wide
// with his project names in it.
out.beforeChecking = api.rowDetailHtml(row(), false);

const key = api._compareKey('c1', 'C:/x/a.esx');
api._compareResults.set(key, { designDiffers: false, renamedOnly: true,
  summary: 'Renamed only - the design is identical, the project just has a different name on each side.' });
out.afterSame = api.rowDetailHtml(row(), false);

api._compareResults.set(key, { designDiffers: true, renamedOnly: false,
  summary: 'Real changes: accessPoints (1 changed), a floor plan image.' });
out.afterDiffers = api.rowDetailHtml(row(), false);

out.otherRowUnaffected = api.rowDetailHtml(row({
  cloud: { id: 'c2', name: 'Other', mtime: 200 },
  local: { path: 'C:/x/b.esx', name: 'Other', mtime: 100 } }), false);

process.stdout.write(JSON.stringify(out));
process.exit(0);
"""


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class TheMeasuredAnswerShowsInTheRowTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "probe.js"
            script.write_text(NODE_SCRIPT, encoding="utf-8")
            proc = subprocess.run(["node", str(script), str(CLOUD_JS)],
                                  capture_output=True, timeout=NODE_TIMEOUT_S)
        if proc.returncode != 0:
            raise AssertionError(
                "node failed: " + proc.stderr.decode("utf-8", "replace"))
        cls.out = json.loads(proc.stdout.decode("utf-8", "replace"))

    def test_the_check_is_offered_before_it_has_been_run(self):
        """He has to be able to ask, from the row that prompted the question.

        The row is stale here, so the detail row exists to carry the question
        even though no comparison has run - "appear when a comparison has been
        run, or when the row needs an action"."""
        self.assertIn("checkRealDifference(", self.out["beforeChecking"])
        self.assertIn("Check what differs", self.out["beforeChecking"])

    def test_an_unchecked_row_says_the_answer_is_unknown(self):
        """A later date is not a design change, and saying nothing at all would
        leave the date to imply that it is."""
        self.assertIn("Not compared yet", self.out["beforeChecking"])

    def test_a_clean_result_is_shown_in_the_row(self):
        html = self.out["afterSame"]
        self.assertIn("rd-same", html)
        self.assertIn("Renamed only", html)

    def test_a_real_difference_is_shown_with_what_differs(self):
        """"3 access points and a floor plan image" is the point - a bare
        "differs" would be one more label to distrust."""
        html = self.out["afterDiffers"]
        self.assertIn("rd-differs", html)
        self.assertIn("accessPoints (1 changed)", html)
        self.assertIn("floor plan image", html)

    def test_the_action_is_still_there_beside_it(self):
        """The measured answer outranks the guess; it does not remove the
        action, because he still has to decide what to do about it."""
        self.assertIn("verifyReplaceLocal(", self.out["afterDiffers"])

    def test_re_checking_is_offered_once_an_answer_exists(self):
        self.assertIn(">Re-check<", self.out["afterSame"])

    def test_the_verdict_is_not_repeated_beside_itself(self):
        """The badge used to carry a short form of the verdict, which put
        "same design" next to a sentence already saying so once they shared a
        line. Only visible by rendering it."""
        self.assertNotIn("cmp-same", self.out["afterSame"])
        self.assertNotIn("same design", self.out["afterSame"].lower()
                         .replace("the design", ""))

    def test_the_answer_belongs_to_one_pair_only(self):
        """Keyed by the pair, so a result never bleeds onto another row."""
        self.assertNotIn("rd-same", self.out["otherRowUnaffected"])
        self.assertNotIn("rd-differs", self.out["otherRowUnaffected"])


if __name__ == "__main__":
    unittest.main()
