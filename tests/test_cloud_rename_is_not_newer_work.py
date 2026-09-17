"""The row has to say *which kind* of difference it found.

Renaming a cloud project moves `history.modifiedAt`. The staleness comparison
read that timestamp and nothing else, so a rename produced the same words as
somebody having redesigned the project: "Cloud newer". After renaming a hundred
cloud projects to a new naming convention, the tool reported a hundred projects
with newer work in them, and there was no honest way to answer "is it safe to
pull all of these" - the two cases were indistinguishable on screen.

That is the concrete version of the complaint that the labels cannot be
trusted. One of them was not true.

`build_matches` classifies the difference now, and this asserts the row renders
that classification rather than merely carrying it. The badge is what gets read,
so the badge is what is tested - through the real function, sliced out of
`cloud.js` and run in Node, which is the pattern `test_cloud_owner_filter.py`
established for exactly this reason: asserting on the source would pass while
the rendered result said something else.
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

// Only what the badge needs. Keeping the slice narrow means a failure here is
// about the badge rather than about everything else the page does.
const block = slice('const MATCH_BADGE_SPEC = {', '\nfunction gutCell(r)');

const WD = {
  esc: s => String(s == null ? '' : s),
  escAttr: s => String(s == null ? '' : s),
  escJsStr: s => String(s == null ? '' : s),
};
function e(s) { return WD.esc(s); }
function a(s) { return WD.escAttr(s); }
function j(s) { return WD.escJsStr(s); }
function pj(s) { return j(String(s == null ? '' : s).replace(/\\/g, '/')); }
let currentTab = 'projects';

const fn = new Function('WD', 'e', 'a', 'j', 'pj', 'currentTab',
  block + '\nreturn { stalenessBadgeHtml, canPullFromCloud };');
const api = fn(WD, e, a, j, pj, currentTab);

const row = (over) => Object.assign({
  kind: 'projects',
  matchType: 'id',
  staleness: 'cloud_newer',
  differenceKind: null,
  cloud: { id: 'c1', name: 'SITE1 New Convention', mtime: 200 },
  local: { path: 'C:/x/a.esx', name: 'SITE1 Old Name', mtime: 100 },
}, over || {});

const out = {
  renamed: api.stalenessBadgeHtml(row({ differenceKind: 'renamed' })),
  content: api.stalenessBadgeHtml(row({ differenceKind: 'content' })),
  unknown: api.stalenessBadgeHtml(row({ differenceKind: null })),
  inSync: api.stalenessBadgeHtml(row({ staleness: null })),
};
process.stdout.write(JSON.stringify(out));
"""


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class TheRowSaysWhichKindOfDifferenceTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "probe.js"
            script.write_text(NODE_SCRIPT, encoding="utf-8")
            proc = subprocess.run(
                ["node", str(script), str(CLOUD_JS)],
                capture_output=True, timeout=NODE_TIMEOUT_S)
        if proc.returncode != 0:
            raise AssertionError(
                "node failed: " + proc.stderr.decode("utf-8", "replace"))
        cls.out = json.loads(proc.stdout.decode("utf-8", "replace"))

    def test_a_rename_does_not_claim_there_is_newer_work(self):
        """The whole point. "Renamed" and "newer" are different statements and
        the row used to make only one of them."""
        self.assertIn("Cloud renamed", self.out["renamed"])
        self.assertNotIn("Cloud newer", self.out["renamed"])

    def test_real_newer_work_still_says_newer(self):
        """The distinction is worthless if it swallows the real case."""
        self.assertIn("Cloud newer", self.out["content"])
        self.assertNotIn("Cloud renamed", self.out["content"])

    def test_the_two_give_different_reasons_not_just_different_words(self):
        """A label that changed while the explanation stayed generic would be
        cosmetic. The tooltip has to carry the evidence too."""
        self.assertIn("RENAMED", self.out["renamed"])
        self.assertIn("No design change was detected", self.out["renamed"])
        self.assertIn("real change rather than a rename", self.out["content"])

    def test_an_unclassified_difference_keeps_the_old_wording(self):
        """When the internal name could not be read, the tool knows nothing
        extra and must not imply that it does - either way round."""
        self.assertIn("Cloud newer", self.out["unknown"])
        self.assertNotIn("Cloud renamed", self.out["unknown"])

    def test_both_remain_actionable(self):
        """A renamed pair still needs pulling to reconcile, so the badge stays
        a button rather than becoming a passive label."""
        for key in ("renamed", "content"):
            self.assertIn("verifyReplaceLocal", self.out[key])

    def test_a_pair_in_sync_renders_nothing(self):
        self.assertEqual("", self.out["inSync"])

    def test_the_backups_location_is_stated_correctly(self):
        """The old wording said the previous copy is kept "alongside it as a
        .previous- file". It has not been alongside since backups moved into
        their own folder, and telling someone the wrong place to look for the
        copy of the file you just overwrote is the worst line in the dialog to
        have wrong."""
        for key in ("renamed", "content"):
            self.assertIn("backups folder", self.out[key])
            self.assertNotIn("alongside it", self.out[key])


if __name__ == "__main__":
    unittest.main()
