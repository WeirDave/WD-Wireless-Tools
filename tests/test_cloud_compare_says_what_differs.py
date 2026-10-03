"""A comparison that finds differences says what they are.

"It says real changes access points and antenna types application profiles
areas and 13 more" - "We don't have the ability to expand that row there's no
details."

The result carried a count per part of the project and the row threw it away,
so seventeen differing parts could not be told apart from three moved access
points. Two facts are added and shown:

* which **fields** differ on the changed items - names only, never values
* how many items are the **same item under a new ID**, because items are
  matched by id and a re-numbering save reads as everything deleted and added

Every name here is invented.
"""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import unittest
import zipfile
from pathlib import Path

from tools.esx_compare import compare_esx

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 120


def _esx(aps):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("project.json", json.dumps(
            {"project": {"id": "p1", "name": "SITE1 Riverside"}}))
        z.writestr("accessPoints.json", json.dumps({"accessPoints": aps}))
    return buf.getvalue()


def _ap(i, x=1.0, ident=None):
    return {"id": ident or "ap-%d" % i, "name": "AP-%03d" % i,
            "location": {"x": x, "y": 2.0}}


class TheResultNamesTheFieldsTests(unittest.TestCase):

    def _ap_diff(self, local, cloud):
        out = compare_esx(_esx(local), _esx(cloud))
        self.assertTrue(out["designDiffers"], out)
        return next(d for d in out["differences"]
                    if d["member"] == "accessPoints.json")

    def test_a_moved_access_point_names_the_field_that_moved(self):
        d = self._ap_diff([_ap(1), _ap(2)], [_ap(1, x=9.0), _ap(2)])
        self.assertEqual(1, d["changed"])
        self.assertEqual(["location"], d["fields"])

    def test_values_never_appear(self):
        """It reaches the page and the log; a value can be a real name."""
        d = self._ap_diff([_ap(1)], [dict(_ap(1), name="AP-SECRET")])
        self.assertEqual(["name"], d["fields"])
        self.assertNotIn("AP-SECRET", json.dumps(d))

    def test_a_renumbered_item_is_recognised(self):
        d = self._ap_diff([_ap(1), _ap(2)],
                          [_ap(1, ident="new-1"), _ap(2, ident="new-2")])
        self.assertEqual((2, 2, 2), (d["added"], d["removed"], d["newIdsOnly"]))

    def test_a_real_replacement_is_not_called_a_new_id(self):
        d = self._ap_diff([_ap(1)], [_ap(1, x=5.0, ident="new-1")])
        self.assertEqual(0, d["newIdsOnly"])


NODE_SCRIPT = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
const a = source.indexOf('function compareDetailsHtml(');
if (a < 0) throw new Error('compareDetailsHtml moved');
let b = a, depth = 0, seen = false;
while (b < source.length && !(seen && depth === 0)) {
  if (source[b] === '{') { depth++; seen = true; }
  else if (source[b] === '}') depth--;
  b++;
}
function e(s) { return String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/</g, '&lt;'); }
eval(source.slice(a, b));
const cmp = { designDiffers: true, differences: [
  { member: 'accessPoints.json', state: 'differs', noun: 'accessPoints',
    added: 0, removed: 0, changed: 3, newIdsOnly: 0, fields: ['location'] },
  { member: 'antennaTypes.json', state: 'differs', noun: 'antennaTypes',
    added: 4, removed: 4, changed: 0, newIdsOnly: 4, fields: [] },
  { member: 'image-1', state: 'differs', kind: 'floor plan image' },
]};
console.log(JSON.stringify({
  shown: compareDetailsHtml(cmp),
  same: compareDetailsHtml({ designDiffers: false, differences: cmp.differences }),
  stored: compareDetailsHtml({ designDiffers: true }),
}));
"""


class TheRowShowsItTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not shutil.which("node"):
            raise unittest.SkipTest("node is not installed")
        r = subprocess.run(["node", "-e", NODE_SCRIPT, str(CLOUD_JS)],
                           capture_output=True, encoding="utf-8",
                           timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        cls.out = json.loads(r.stdout)

    def test_each_part_gets_a_line_he_can_read(self):
        html = self.out["shown"]
        self.assertIn("<details", html)
        self.assertIn("What differs (3)", html)
        self.assertIn("access points: 3 changed - fields: location", html)
        self.assertIn("antenna types: 4 only in local, 4 only in cloud "
                      "(4 of those are the same item under a new ID)", html)
        self.assertIn("A floor plan image differs.", html)

    def test_nothing_is_drawn_when_the_design_matches(self):
        self.assertEqual("", self.out["same"])

    def test_a_remembered_verdict_without_detail_draws_nothing(self):
        """Stored comparisons keep the summary only; an empty box would read
        as "nothing differs"."""
        self.assertEqual("", self.out["stored"])


ROW_SCRIPT = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
const block = slice('function ownershipBlock(', '\nfunction _isExternal(')
            + slice('function comparisonIsSettled(', '\nfunction isOutOfSync(')
            + slice('const ICONS = {', '\nfunction siteDigest(')
            + slice('const MATCH_BADGE_SPEC = {', '\nfunction gutCell(r)');
const WD = { esc: s => String(s == null ? '' : s),
             escAttr: s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;'),
             escJsStr: s => String(s == null ? '' : s) };
function e(s) { return WD.esc(s); }
function a(s) { return WD.escAttr(s); }
function np(s) { return String(s == null ? '' : s).replace(/\\/g, '/'); }
function p(s) { return a(np(s)); }
const noop = () => {};
const fn = new Function('WD','e','a','p','np','currentTab','opEnqueue','toast','pyApi','showConfirmModal','_clearStaleness','_scheduleOpRefresh','selectedSyncItems','clearSelection','renderRows',
  block + '\nreturn { rowDetailHtml, _compareResults, _compareKey };');
const api = fn(WD,e,a,p,np,'projects',noop,noop,async()=>({}),async()=>true,noop,noop,()=>[],noop,noop);
const row = { kind: 'projects', matchType: 'id', staleness: 'cloud_newer',
  cloud: { id: 'c1', name: 'SITE1 Riverside', mtime: 200 },
  local: { path: 'C:/projects/SITE1/SITE1 Riverside.esx', name: 'SITE1 Riverside', mtime: 100 } };
api._compareResults.set(api._compareKey('c1', row.local.path), {
  designDiffers: true, summary: 'Real changes: accessPoints (3 changed).',
  differences: [{ member: 'accessPoints.json', state: 'differs', noun: 'accessPoints',
                  added: 0, removed: 0, changed: 3, newIdsOnly: 0, fields: ['location'] }],
  cloudMtime: 200, localMtime: 100 });
console.log(JSON.stringify({ html: api.rowDetailHtml(row, false) }));
"""


class TheListIsOnTheRealRowTests(unittest.TestCase):

    def test_the_row_band_carries_it(self):
        if not shutil.which("node"):
            self.skipTest("node is not installed")
        r = subprocess.run(["node", "-e", ROW_SCRIPT, str(CLOUD_JS)],
                           capture_output=True, encoding="utf-8",
                           timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        html = json.loads(r.stdout)["html"]
        self.assertIn("Real changes", html)
        self.assertIn("access points: 3 changed - fields: location", html)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
