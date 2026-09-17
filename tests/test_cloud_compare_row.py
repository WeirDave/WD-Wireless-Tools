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
const block = slice('const MATCH_BADGE_SPEC = {', '\nfunction gutCell(r)');

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
  block + '\nreturn { stalenessBadgeHtml, _compareResults, _compareKey };');
const api = fn(WD,e,a,j,pj,currentTab,opEnqueue,toast,pyApi,_clearStaleness,_scheduleOpRefresh,selectedSyncItems,clearSelection);

const row = (over) => Object.assign({
  kind: 'projects', matchType: 'id', staleness: 'cloud_newer',
  differenceKind: 'renamed',
  cloud: { id: 'c1', name: 'SITE1 New', mtime: 200 },
  local: { path: 'C:/x/a.esx', name: 'SITE1 Old', mtime: 100 },
}, over || {});

const out = {};
out.beforeChecking = api.stalenessBadgeHtml(row());

const key = api._compareKey('c1', 'C:/x/a.esx');
api._compareResults.set(key, { designDiffers: false, renamedOnly: true,
  summary: 'Renamed only - the design is identical, the project just has a different name on each side.' });
out.afterSame = api.stalenessBadgeHtml(row());

api._compareResults.set(key, { designDiffers: true, renamedOnly: false,
  summary: 'Real changes: accessPoints (1 changed), a floor plan image.' });
out.afterDiffers = api.stalenessBadgeHtml(row());

out.otherRowUnaffected = api.stalenessBadgeHtml(row({
  cloud: { id: 'c2', name: 'Other', mtime: 200 },
  local: { path: 'C:/x/b.esx', name: 'Other', mtime: 100 } }));

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
        """He has to be able to ask, from the row that prompted the question."""
        self.assertIn("checkRealDifference(", self.out["beforeChecking"])
        self.assertIn(">Check<", self.out["beforeChecking"])

    def test_the_offer_says_it_changes_nothing(self):
        """It downloads a whole project; without that sentence it reads like
        another sync button, which is the last thing to guess wrong about."""
        self.assertIn("Nothing is changed on either side",
                      self.out["beforeChecking"])

    def test_a_clean_result_is_shown_in_the_row(self):
        html = self.out["afterSame"]
        self.assertIn("cmp-same", html)
        self.assertIn("Renamed only", html)

    def test_a_real_difference_is_shown_with_what_differs(self):
        """"3 access points and a floor plan image" is the point - a bare
        "differs" would be one more label to distrust."""
        html = self.out["afterDiffers"]
        self.assertIn("cmp-differs", html)
        self.assertIn("accessPoints (1 changed)", html)
        self.assertIn("floor plan image", html)

    def test_the_inferred_badge_is_still_there_beside_it(self):
        """The measured answer outranks the guess; it does not remove the
        action, because he still has to decide what to do about it."""
        self.assertIn("verifyReplaceLocal(", self.out["afterDiffers"])

    def test_re_checking_is_offered_once_an_answer_exists(self):
        self.assertIn(">Re-check<", self.out["afterSame"])

    def test_the_answer_belongs_to_one_pair_only(self):
        """Keyed by the pair, so a result never bleeds onto another row."""
        self.assertNotIn("cmp-same", self.out["otherRowUnaffected"])
        self.assertNotIn("cmp-differs", self.out["otherRowUnaffected"])


if __name__ == "__main__":
    unittest.main()
