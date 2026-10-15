"""Two buttons that answer one question look like one question.

A row that asks "which side wins?" offers one button per direction, and the
band draws each under the side it writes to. The two used to disagree about
weight, row to row and in no consistent direction:

* a project whose names disagree filled **Cloud -> Local** and left
  **Local -> Cloud** outlined
* a site whose names disagree did the opposite, filling **Local -> Cloud**
* a renamed folder filled the cloud rename only
* "the cloud is newer" paired a filled download with **Replace cloud with
  local...** in the `quiet` style, which has no border and no background, so
  it did not read as a button at all - "I couldn't even tell that was a button"

Nothing about those rows recommends a direction; the sentence says "pick the
one to keep". So the pair is drawn as a pair: same classes on both. Emphasis
stays with the read-only check, the one action in the band with an opinion
behind it.

**Rendered, not searched.** Each row is built by the real functions and the
buttons are read back out of the markup, so a weight set anywhere along the
way is seen. Nothing here asserts that a source string exists.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 120

NODE_SCRIPT = r"""
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
             escAttr: s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/'/g, '&#39;').replace(/"/g, '&quot;').replace(/</g, '&lt;').replace(/>/g, '&gt;'),
             escJsStr: s => String(s == null ? '' : s) };
function e(s) { return WD.esc(s); }
function a(s) { return WD.escAttr(s); }
function np(s) { return String(s == null ? '' : s).replace(/\\/g, '/'); }
function p(s) { return a(np(s)); }
function opEnqueue() { return { id: 'op1', promise: Promise.resolve() }; }
function toast() {}
async function pyApi() { return { ok: true }; }
async function showConfirmModal() { return true; }
function _clearStaleness() {}
function renderRows() {}
function _scheduleOpRefresh() {}
function selectedSyncItems() { return []; }
function clearSelection() {}

const fn = new Function('WD','e','a','p','np','currentTab','opEnqueue','toast','pyApi','showConfirmModal','_clearStaleness','_scheduleOpRefresh','selectedSyncItems','clearSelection','renderRows',
  'var data = {};\n' + block
  + '\nreturn { rowDetailHtml, _compareResults, _compareKey, setData: d => { data = d; } };');
const api = fn(WD,e,a,p,np,'projects',opEnqueue,toast,pyApi,showConfirmModal,_clearStaleness,_scheduleOpRefresh,selectedSyncItems,clearSelection,renderRows);

/* Every button in a band that names a side, read back out of the markup. */
function buttons(html) {
  const out = [];
  const re = /<button class="([^"]*)"([^>]*)>[\s\S]*?<span>([\s\S]*?)<\/span><\/button>/g;
  let m;
  while ((m = re.exec(html))) {
    const w = /data-writes="(cloud|local)"/.exec(m[2]);
    out.push({ cls: m[1].split(/\s+/).filter(Boolean), writes: w ? w[1] : '', label: m[3] });
  }
  return out;
}

// Filed under the site that matches its folder, so no location question
// joins the band and muddies which pair is under test.
const cloud = { id: 'c1', name: 'Project A', mtime: 100, siteName: 'Folder B', siteId: 's2' };
const localPath = 'C:/projects/Folder B/Project A.esx';
const local = { path: localPath, name: 'Project A', mtime: 200, folder: 'Folder B' };
const out = {};

// names disagree - a project and a site
out.projectMismatch = buttons(api.rowDetailHtml({
  kind: 'projects', status: 'mismatch', matchType: 'id',
  cloud: { id: 'c1', name: 'Project A' },
  local: { path: localPath, name: 'Project B' },
}, false));
out.siteMismatch = buttons(api.rowDetailHtml({
  kind: 'sites', status: 'mismatch', matchType: 'id',
  cloud: { id: 's1', name: 'Site A' },
  local: { path: 'C:/projects/Folder B', name: 'Folder B' },
}, false));

// the cloud copy is newer: unchecked, then checked and different, then renamed
const cloudNewer = (extra) => Object.assign({
  kind: 'projects', status: 'synced', matchType: 'id',
  staleness: 'cloud_newer', differenceKind: 'content',
  cloud: Object.assign({}, cloud, { mtime: 300 }), local,
}, extra || {});
out.cloudNewerUnchecked = buttons(api.rowDetailHtml(cloudNewer(), false));
api._compareResults.set(api._compareKey('c1', localPath),
  { designDiffers: true, summary: 'Differs.' });
out.cloudNewerDiffers = buttons(api.rowDetailHtml(cloudNewer(), false));
api._compareResults.clear();
out.cloudNewerRenamed = buttons(api.rowDetailHtml(cloudNewer({ differenceKind: 'renamed' }), false));

// a lone push, before and after a comparison
const localNewer = () => ({
  kind: 'projects', status: 'synced', matchType: 'id',
  staleness: 'local_newer', differenceKind: 'content', cloud, local,
});
out.localNewerUnchecked = buttons(api.rowDetailHtml(localNewer(), false));

// the project and its cloud site live in different places
const placed = (siteName) => ({
  kind: 'projects', status: 'synced', matchType: 'id',
  cloud: { id: 'c1', name: 'Project A', siteName, siteId: 's1' }, local,
});
api.setData({ siteIds: { 'Site A': 's1', 'Folder B': 's2' }, matched: [], localOnly: [] });
out.moved = buttons(api.rowDetailHtml(placed('Site A'), false));
api.setData({
  siteIds: { 'Site A': 's1' },
  matched: [{ cloud: { siteId: 's1' }, local: { folder: 'Folder B' } }],
  localOnly: [],
});
out.folderRenamed = buttons(api.rowDetailHtml(placed('Site A'), false));

process.stdout.write(JSON.stringify(out));
"""

# State classes describe the situation a button is in, not how heavy it is.
STATE = {"is-renamed", "is-demoted", "is-disabled"}


def weight(button):
    return sorted(c for c in button["cls"] if c not in STATE and c != "rd-btn")


@unittest.skipUnless(shutil.which("node"), "node is required to render the band")
class OppositeButtonsAreMirrors(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        r = subprocess.run(
            ["node", "-e", NODE_SCRIPT, str(CLOUD_JS)],
            capture_output=True, text=True, encoding="utf-8",
            timeout=NODE_TIMEOUT_S,
        )
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        cls.out = json.loads(r.stdout)

    def pair(self, name):
        """The cloud-side and local-side button of a scenario - exactly one
        each, or the scenario is not the pair it claims to be."""
        buttons = self.out[name]
        cloud = [b for b in buttons if b["writes"] == "cloud"]
        local = [b for b in buttons if b["writes"] == "local"]
        self.assertEqual((len(cloud), len(local)), (1, 1),
                         f"{name}: expected one button per side, got "
                         f"{[(b['writes'], b['label']) for b in buttons]}")
        return cloud[0], local[0]

    def test_both_directions_carry_the_same_weight(self):
        for name in ("projectMismatch", "siteMismatch", "cloudNewerUnchecked",
                     "cloudNewerDiffers", "cloudNewerRenamed", "moved",
                     "folderRenamed"):
            with self.subTest(name):
                c, l = self.pair(name)
                self.assertEqual(
                    weight(c), weight(l),
                    f"{name}: '{c['label']}' is {weight(c)} but "
                    f"'{l['label']}' is {weight(l)}")

    def test_a_direction_is_never_drawn_as_bare_text(self):
        """`quiet` has no border and no background. On a direction it is a
        button nobody can see."""
        for name in ("projectMismatch", "siteMismatch", "cloudNewerUnchecked",
                     "cloudNewerDiffers", "cloudNewerRenamed", "moved",
                     "folderRenamed", "localNewerUnchecked"):
            for b in self.out[name]:
                if b["writes"]:
                    with self.subTest(name, label=b["label"]):
                        self.assertNotIn("quiet", b["cls"])

    def test_the_renamed_folder_pair_was_really_rendered(self):
        """The renamed-folder branch needs the page's own data to be reached;
        if the probe's setup stops reaching it this should say so rather than
        let the mirror check pass on the other branch."""
        labels = {b["label"] for b in self.out["folderRenamed"] if b["writes"]}
        self.assertEqual(labels, {"Rename folder to match",
                                  "Rename cloud site to match"})
        labels = {b["label"] for b in self.out["moved"] if b["writes"]}
        self.assertEqual(labels, {"Move file to match",
                                  "Move cloud project to match"})


if __name__ == "__main__":
    unittest.main()
