"""A folder renamed on disk can be pushed up as the cloud site's new name.

A site row had no detail band. Every other matched row that disagreed on a
name carried **Cloud → Local** and **Local → Cloud** in the band beneath it;
a site row carried nothing, so renaming a folder locally left no control that
renamed the cloud site to match.

That only became a dead end in v2.176.0, which is why it is worth writing down.
Sites have no Ekahau id, so a folder that has been renamed can pair with its
site only by a shared site code or similar wording - a *guessed* pairing. Bulk
Local → Cloud stopped renaming guessed pairings in that release, and its
message told him to "use the row's own Local → Cloud". On a site row there was
no such control. The one route up was the one the tool refused.

The bulk refusal is right: nobody reads the rows in a bulk run. The row is where
the two names sit side by side, which is the check the refusal asks for, so the
row offers the rename.

Driven, not grepped: the real row renderer draws the band, each control is read
back out of that markup, and the real `syncRow` runs against a recording
`pyApi`. What is asserted is the call that reaches the server.

The second half is the same guard's other hole. `indexRowData` stamped every
top-level pair `entityKind: 'sites'`, including on the Projects tab, and the
planner skips the ownership check for sites. So on the Projects tab a
colleague's project went into a Local → Cloud rename run and Ekahau answered
403. Every name and address here is invented.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

from tests.delegated import DELEGATED_JS

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 120

PROGRAM = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
function fakeEl() {
  return { innerHTML: '', textContent: '', value: '', checked: false,
    hidden: false, disabled: false, dataset: {}, style: {}, children: [],
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    addEventListener(){}, setAttribute(){}, getAttribute(){ return null; },
    querySelector(){ return null; }, querySelectorAll(){ return []; },
    appendChild(){}, remove(){}, focus(){}, click(){} };
}
const sandbox = {
  console, JSON, Math, Date, Map, Set, Promise, RegExp, Intl,
  setTimeout, clearTimeout, setInterval, clearInterval,
  document: { getElementById(){ return fakeEl(); },
    querySelector(){ return fakeEl(); }, querySelectorAll(){ return []; },
    createElement(){ return fakeEl(); }, addEventListener(){},
    body: fakeEl(), documentElement: fakeEl() },
  navigator: { platform: 'Win32', clipboard: { writeText: async () => {} } },
  location: { href: 'file:///cloud.html', search: '', hash: '' },
  localStorage: { getItem: () => null, setItem(){}, removeItem(){} },
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  alert(){}, confirm(){ return true; },
  requestAnimationFrame: (f) => setTimeout(f, 0),
  WD: { esc: s => String(s == null ? '' : s).replace(/[&<>"]/g,
          c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])),
        applyVersions(){}, toast(){} },
};
sandbox.WD.escAttr = sandbox.WD.esc;
sandbox.WD.escJsStr = s => String(s == null ? '' : s).replace(/['\\]/g, '\\$&');
sandbox.window = sandbox;
vm.createContext(sandbox);
try { vm.runInContext(source, sandbox, { filename: 'cloud.js' }); }
catch (err) { if (!/addEventListener|null|undefined/.test(err.message)) throw err; }
""" + DELEGATED_JS + r"""

const ME = 'me@example.invalid';
const THEM = 'colleague@example.invalid';
const mode = process.argv[2];
const input = JSON.parse(process.argv[3]);

vm.runInContext("data = {currentUser:'" + ME + "',matched:[],cloudOnly:[],"
  + "localOnly:[],orphans:{cloudOnly:[],localOnly:[]}};"
  + "currentTab = 'sites'; activeFilter = 'all';", sandbox);

const calls = [];
sandbox.pyApi = async (...args) => { calls.push(args); return { ok: true }; };
sandbox.opEnqueue = (spec) => ({ promise: Promise.resolve(spec.run('op-1')) });
sandbox._scheduleOpRefresh = () => {};
sandbox.markNotMatch = (...args) => { calls.push(['markNotMatch'].concat(args)); };

(async () => {
  if (mode === 'band') {
    sandbox.__row = input;
    const html = vm.runInContext('rowDetailHtml(__row, 0)', sandbox);
    const buttons = String(html).match(/<button class="rd-btn[\s\S]*?<\/button>/g) || [];
    const byLabel = {};
    for (const b of buttons) {
      const label = (b.match(/<span>([^<]*)<\/span><\/button>$/) || [])[1] || '';
      const fn = (b.match(/data-fn="([^"]*)"/) || [])[1] || '';
      const writes = (b.match(/data-writes="([^"]*)"/) || [])[1] || '';
      const hit = fn ? delegated(b, fn) : null;
      byLabel[label] = { fn, writes, disabled: hit ? hit.disabled : true,
                         args: hit ? hit.args : [] };
    }
    const results = {};
    for (const label of Object.keys(byLabel)) {
      const c = byLabel[label];
      if (!c.fn || c.disabled) continue;
      calls.length = 0;
      await sandbox[c.fn].apply(null, c.args);
      results[label] = calls.slice();
    }
    process.stdout.write(JSON.stringify({ html, controls: byLabel, results }));
    return;
  }
  if (mode === 'plan') {
    vm.runInContext("currentTab = " + JSON.stringify(input.tab) + ";", sandbox);
    sandbox.__matched = input.matched;
    vm.runInContext('data.matched = __matched; indexRowData();', sandbox);
    //: `rowData` is a `let`, so it lives in the context's scope rather than
    //: on the global object.
    const items = vm.runInContext(
      "__matched.map(p => rowData['p:' + p.cloud.id])", sandbox);
    if (items.some(d => !d)) throw new Error('indexRowData wrote no p: row');
    sandbox.__items = items;
    const plan = vm.runInContext("syncPlan(__items, 'to-cloud')", sandbox);
    process.stdout.write(JSON.stringify({
      entityKinds: items.map(d => d.entityKind),
      renamed: plan.pairs.map(d => d.cloudId),
      refused: plan.blockedRenames.map(d => [d.cloudId, d.refusal]),
    }));
    return;
  }
  throw new Error('unknown mode ' + mode);
})().catch(err => { console.error(err.stack || err.message); process.exit(1); });
"""


def run(mode, payload):
    r = subprocess.run(
        ["node", "-e", PROGRAM, str(CLOUD_JS), mode, json.dumps(payload)],
        capture_output=True, text=True, encoding="utf-8",
        timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip()[-2500:])
    return json.loads(r.stdout.strip().splitlines()[-1])


FOLDER = "D:/Esx/SITE7 Harbour Annex"


def site_row(*, status="mismatch", match_type="code"):
    return {"kind": "sites", "status": status, "matchType": match_type,
            "cloud": {"id": "site-7", "name": "SITE7 Harbour", "owner": ""},
            "local": {"path": FOLDER, "name": "SITE7 Harbour Annex",
                      "isDir": True}}


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class ASiteRowCarriesTheRenameTests(unittest.TestCase):

    def test_local_to_cloud_renames_the_cloud_site_to_the_folder_name(self):
        """The case reported: the folder was renamed, the site was not."""
        got = run("band", site_row())
        self.assertIn("Local → Cloud", got["controls"], got["html"][:600])
        self.assertEqual("cloud", got["controls"]["Local → Cloud"]["writes"])
        self.assertEqual(
            [["rename_cloud", "sites", "site-7", "SITE7 Harbour Annex"]],
            got["results"]["Local → Cloud"])

    def test_cloud_to_local_renames_the_folder_to_the_site_name(self):
        got = run("band", site_row())
        self.assertEqual("local", got["controls"]["Cloud → Local"]["writes"])
        self.assertEqual([["rename_local", FOLDER, "SITE7 Harbour"]],
                         got["results"]["Cloud → Local"])

    def test_not_a_match_is_offered_with_both_sides(self):
        got = run("band", site_row())
        self.assertEqual(
            [["markNotMatch", "site-7", FOLDER, "SITE7 Harbour",
              "SITE7 Harbour Annex"]],
            got["results"]["Not a match"])

    def test_a_guessed_pairing_says_so_on_the_row(self):
        """The row is offered because the two names can be checked here, so
        it has to say that they should be."""
        got = run("band", site_row(match_type="fuzzy"))
        self.assertIn("check both names", got["html"])
        got = run("band", site_row(match_type="exact"))
        self.assertNotIn("check both names", got["html"])

    def test_a_site_whose_names_agree_has_no_band(self):
        """A second line means a row wants something. A settled site that
        grew one would put noise on every row of the tree."""
        got = run("band", site_row(status="synced", match_type="exact"))
        self.assertEqual("", got["html"])


def pair(cid, *, is_dir, owner, match_type="id"):
    local_path = ("D:/Esx/" + cid) if is_dir else ("D:/Esx/" + cid + ".esx")
    return {"cloud": {"id": cid, "name": cid + " Old", "owner": owner},
            "local": {"path": local_path, "name": cid + " New",
                      "isDir": is_dir, "owner": owner},
            "matchType": match_type, "namesDiffer": True, "staleness": None}


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class TheOwnershipGuardSeesProjectsTests(unittest.TestCase):

    THEM = "colleague@example.invalid"
    ME = "me@example.invalid"

    def test_a_colleagues_project_on_the_projects_tab_is_refused(self):
        got = run("plan", {"tab": "projects",
                           "matched": [pair("proj-1", is_dir=False,
                                            owner=self.THEM)]})
        self.assertEqual(["projects"], got["entityKinds"])
        self.assertEqual([], got["renamed"])
        self.assertEqual([["proj-1", "not-mine"]], got["refused"])

    def test_his_own_project_is_still_renamed(self):
        got = run("plan", {"tab": "projects",
                           "matched": [pair("proj-2", is_dir=False,
                                            owner=self.ME)]})
        self.assertEqual(["proj-2"], got["renamed"])

    def test_a_site_is_still_a_site(self):
        """Sites were never ownership-gated, and this must not start doing it."""
        got = run("plan", {"tab": "sites",
                           "matched": [pair("site-9", is_dir=True,
                                            owner=self.THEM,
                                            match_type="exact")]})
        self.assertEqual(["sites"], got["entityKinds"])
        self.assertEqual(["site-9"], got["renamed"])


if __name__ == "__main__":
    unittest.main()
