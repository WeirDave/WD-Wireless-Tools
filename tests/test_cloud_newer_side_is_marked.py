"""Which copy is newer is said on that copy, and the two buttons are mirrors.

A row used to say "The cloud copy has the later date." in a sentence under the
pair, and a reader had to work out which way "later" pointed. Now the copy that
was saved last carries a **Newer** tag beside its date, and the action that
overwrites the *other* copy sits under the side it changes, labelled the same
way in both directions ("Local newer · replace cloud" / "Cloud newer · replace
local") and filled in the same circumstances (once the two were compared).

These run the real renderers out of `cloud.js` in Node.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 120

PROBE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[process.argv.length - 1], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from), b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('slice not found: ' + from);
  return source.slice(a, b);
}
const WD = {
  esc: s => String(s == null ? '' : s).replace(/[&<>"]/g, c =>
    ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),
};
WD.escAttr = WD.esc;
WD.escJsStr = s => String(s == null ? '' : s);
function e(s){return WD.esc(s);} function a(s){return WD.escAttr(s);}
function p(s){return a(String(s==null?'':s).replace(/\\/g,'/'));}
function np(s){return String(s==null?'':s).replace(/\\/g,'/');}
let currentTab='projects', selected=new Set(), activeFilter='all';
const data={currentUser:'me@example.com'};
const navigator={platform:'Win32'};
function charDiff(x,y){return {a:e(x),b:e(y)};}
function dupHintFor(){return '';}
function previewBadge(){return '';}
function canPullFromCloud(r){return ['id','manual','exact'].includes(r.matchType);}
function canPushToCloud(r){return ['id','manual','exact'].includes(r.matchType);}
const block = slice('function comparisonIsSettled(', '\nfunction _isExternal(')
            + slice('const ICONS = {', '\nfunction localByPath(');
const api = {};
eval(block + '\nObject.assign(api,{cloudCell,localCell,rowDetailHtml,_compareKey,_compareResults});');

const cloud = (o) => Object.assign({id:'c1',name:'Alpha Survey',meta:'cloud-meta',mtime:2,owner:'me@example.com'}, o);
const local = (o) => Object.assign({path:'D:/E/Alpha Survey.esx',name:'Alpha Survey',meta:'local-meta',mtime:1}, o);
const pair = (o) => Object.assign({status:'synced',kind:'projects',matchType:'id',
  cloud:cloud(),local:local(),key:'k'}, o);

function lanes(html) {
  const c = html.indexOf('rd-lane cloud'), l = html.indexOf('rd-lane local');
  return { cloud: html.slice(c, l), local: html.slice(l) };
}
function cells(r) { return { cloud: api.cloudCell(r, new Set()), local: api.localCell(r, new Set()) }; }

const out = {};
out.cloudNewer = cells(pair({staleness:'cloud_newer'}));
out.localNewer = cells(pair({staleness:'local_newer'}));
out.inSync     = cells(pair());

const different = { designDiffers: true, summary: 'Real changes: accessPoints (3 changed).',
  differences: [], cloudMtime: 2, localMtime: 1 };
const rc = pair({staleness:'cloud_newer'});
api._compareResults.set(api._compareKey('c1', rc.local.path), Object.assign({}, different));
out.cloudBandCompared = lanes(api.rowDetailHtml(rc, false));
const rl = pair({staleness:'local_newer', cloud: cloud({mtime:1}), local: local({mtime:2})});
api._compareResults.set(api._compareKey('c1', rl.local.path),
  Object.assign({}, different, { cloudMtime: 1, localMtime: 2 }));
out.localBandCompared = lanes(api.rowDetailHtml(rl, false));

out.cloudBandPlain = lanes(api.rowDetailHtml(pair({staleness:'cloud_newer', key:'k2', cloud: cloud({id:'c2'})}), false));
out.localBandPlain = lanes(api.rowDetailHtml(pair({staleness:'local_newer', key:'k3', cloud: cloud({id:'c3'})}), false));

const same = pair({staleness:'cloud_newer', cloud: cloud({id:'c4'})});
api._compareResults.set(api._compareKey('c4', same.local.path),
  { designDiffers: false, identical: true, nameState: 'same', cloudMtime: 2, localMtime: 1 });
out.settled = cells(same);
console.log(JSON.stringify(out));
"""


def _filled(lane_html: str, label: str) -> bool:
    """Is the button carrying `label` drawn with the `primary` class?"""
    i = lane_html.index(label)
    start = lane_html.rindex('<button class="', 0, i)
    classes = lane_html[start + len('<button class="'):].split('"', 1)[0]
    return "primary" in classes.split()


class TheNewerSideIsMarkedTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not shutil.which("node"):
            raise unittest.SkipTest("node is not installed")
        r = subprocess.run(["node", "-e", PROBE, str(CLOUD_JS)],
                           capture_output=True, encoding="utf-8",
                           timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        cls.out = json.loads(r.stdout)

    def test_the_cloud_copy_is_marked_when_it_is_the_newer(self):
        self.assertIn('class="newer-tag"', self.out["cloudNewer"]["cloud"])
        self.assertNotIn("newer-tag", self.out["cloudNewer"]["local"])

    def test_the_local_file_is_marked_when_it_is_the_newer(self):
        self.assertIn('class="newer-tag"', self.out["localNewer"]["local"])
        self.assertNotIn("newer-tag", self.out["localNewer"]["cloud"])

    def test_a_pair_in_step_marks_neither(self):
        self.assertNotIn("newer-tag", self.out["inSync"]["cloud"])
        self.assertNotIn("newer-tag", self.out["inSync"]["local"])

    def test_a_pair_proven_identical_marks_neither(self):
        self.assertNotIn("newer-tag", self.out["settled"]["cloud"])
        self.assertNotIn("newer-tag", self.out["settled"]["local"])

    def test_the_tag_sits_beside_the_date_it_is_about(self):
        html = self.out["cloudNewer"]["cloud"]
        self.assertLess(html.index("newer-tag"), html.index("cloud-meta"))

    def test_each_button_is_under_the_side_it_changes(self):
        self.assertIn("Local newer · replace cloud", self.out["localBandPlain"]["cloud"])
        self.assertNotIn("Local newer · replace cloud", self.out["localBandPlain"]["local"])
        self.assertIn("Cloud newer · replace local", self.out["cloudBandPlain"]["local"])
        self.assertNotIn("Cloud newer · replace local", self.out["cloudBandPlain"]["cloud"])

    def test_the_old_download_wording_is_gone(self):
        for k in ("cloudBandPlain", "cloudBandCompared"):
            for lane in ("cloud", "local"):
                self.assertNotIn("· download", self.out[k][lane])

    def test_both_mirrors_are_filled_once_compared_and_not_before(self):
        self.assertTrue(_filled(self.out["localBandCompared"]["cloud"],
                                "Local newer · replace cloud"))
        self.assertTrue(_filled(self.out["cloudBandCompared"]["local"],
                                "Cloud newer · replace local"))
        self.assertFalse(_filled(self.out["localBandPlain"]["cloud"],
                                 "Local newer · replace cloud"))
        self.assertFalse(_filled(self.out["cloudBandPlain"]["local"],
                                 "Cloud newer · replace local"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
