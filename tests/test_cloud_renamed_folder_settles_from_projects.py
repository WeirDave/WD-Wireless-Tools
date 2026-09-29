"""A folder renamed on disk can be settled from the Projects tab.

"if you rename a folder on your drive it shows changed local against the
cloud version but there is no way to change the cloud to match the local."

On the Projects tab a project whose cloud site and local folder disagree drew
both names on the row and offered nothing. A renamed folder puts every project
inside it in that state at once. The Sites tab can rename the site only while
the renamed folder still pairs with it, and a big enough rename unpairs them.

The row now tells a renamed folder from a moved file and offers the fix for
each: rename the cloud site (or the folder back), or move one side to the
other's location. Driven, not grepped - the real renderer draws the band, each
control is read back out of that markup and run against a recording `pyApi`,
and what is asserted is the call that reaches the server. Every name here is
invented.
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
const input = JSON.parse(process.argv[3]);

sandbox.__data = Object.assign({currentUser: ME, matched: [], cloudOnly: [],
  localOnly: [], orphans: {cloudOnly: [], localOnly: []}}, input.data);
vm.runInContext("data = __data; currentTab = 'projects'; activeFilter = 'all';", sandbox);

const calls = [];
sandbox.pyApi = async (...args) => { calls.push(args); return { ok: true }; };
sandbox.opEnqueue = (spec) => ({ promise: Promise.resolve(spec.run('op-1')) });
sandbox._scheduleOpRefresh = () => {};

(async () => {
  sandbox.__row = input.row;
  const html = vm.runInContext('rowDetailHtml(__row, 0)', sandbox);
  const buttons = String(html).match(/<button class="rd-btn[\s\S]*?<\/button>/g) || [];
  const byLabel = {};
  for (const b of buttons) {
    const label = (b.match(/<span>([^<]*)<\/span><\/button>$/) || [])[1] || '';
    const fn = (b.match(/data-fn="([^"]*)"/) || [])[1] || '';
    const writes = (b.match(/data-writes="([^"]*)"/) || [])[1] || '';
    const hit = fn ? delegated(b, fn) : null;
    byLabel[label] = { fn, writes, disabled: !hit || hit.disabled,
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
})().catch(err => { console.error(err.stack || err.message); process.exit(1); });
"""


def run(payload):
    r = subprocess.run(
        ["node", "-e", PROGRAM, str(CLOUD_JS), "band", json.dumps(payload)],
        capture_output=True, text=True, encoding="utf-8",
        timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip()[-2500:])
    return json.loads(r.stdout.strip().splitlines()[-1])


ME = "me@example.invalid"
THEM = "colleague@example.invalid"
ROOT_DIR = "D:/Esx"


def pair(pid, *, site, site_id, folder, owner=ME):
    return {"cloud": {"id": pid, "name": pid, "owner": owner,
                      "siteName": site, "siteId": site_id},
            "local": {"path": f"{ROOT_DIR}/{folder}/{pid}.esx", "name": pid,
                      "folder": folder, "isDir": False},
            "matchType": "id", "namesDiffer": False, "staleness": None}


def row_of(p):
    return {"status": "synced", "kind": "projects", "matchType": "id",
            "cloud": p["cloud"], "local": p["local"]}


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class ARenamedFolderRenamesTheSiteTests(unittest.TestCase):

    def setUp(self):
        self.a = pair("SITE3 Survey", site="SITE3 Dockside",
                      site_id="site-3", folder="SITE3 Dockside North")
        self.b = pair("SITE3 Design", site="SITE3 Dockside",
                      site_id="site-3", folder="SITE3 Dockside North")
        self.data = {"matched": [self.a, self.b],
                     "siteIds": {"SITE3 Dockside": "site-3"}}

    def test_local_to_cloud_renames_the_site_to_the_folder_name(self):
        got = run({"data": self.data, "row": row_of(self.a)})
        ctl = got["controls"].get("Rename cloud site to match")
        self.assertIsNotNone(ctl, got["html"][:800])
        self.assertEqual("cloud", ctl["writes"])
        self.assertEqual(
            [["rename_cloud", "sites", "site-3", "SITE3 Dockside North"]],
            got["results"]["Rename cloud site to match"])

    def test_cloud_to_local_renames_the_folder_back(self):
        got = run({"data": self.data, "row": row_of(self.a)})
        self.assertEqual("local",
                         got["controls"]["Rename folder to match"]["writes"])
        self.assertEqual(
            [["rename_local", ROOT_DIR + "/SITE3 Dockside North",
              "SITE3 Dockside"]],
            got["results"]["Rename folder to match"])

    def test_the_row_names_both_names(self):
        got = run({"data": self.data, "row": row_of(self.a)})
        self.assertIn("SITE3 Dockside North", got["html"])
        self.assertIn("folder looks renamed", got["html"])

    def test_a_windows_path_reaches_the_server_with_forward_slashes(self):
        a = json.loads(json.dumps(self.a))
        a["local"]["path"] = a["local"]["path"].replace("/", "\\")
        got = run({"data": {"matched": [a],
                            "siteIds": self.data["siteIds"]},
                   "row": row_of(a)})
        self.assertEqual(
            [["rename_local", ROOT_DIR + "/SITE3 Dockside North",
              "SITE3 Dockside"]],
            got["results"]["Rename folder to match"])


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class AMovedFileIsNotARenameTests(unittest.TestCase):
    """Renaming a site because one file moved would rename it for every other
    project still sitting in the old folder."""

    def test_a_site_split_across_folders_is_not_renamed(self):
        moved = pair("SITE4 Survey", site="SITE4 Quay", site_id="site-4",
                     folder="SITE4 Quay Annex")
        stayed = pair("SITE4 Design", site="SITE4 Quay", site_id="site-4",
                      folder="SITE4 Quay")
        got = run({"data": {"matched": [moved, stayed],
                            "siteIds": {"SITE4 Quay": "site-4"}},
                   "row": row_of(moved)})
        self.assertNotIn("Rename cloud site to match", got["controls"])
        self.assertEqual(
            [["move_local_to_site", ROOT_DIR + "/SITE4 Quay Annex/SITE4 Survey.esx",
              "SITE4 Quay"]],
            got["results"]["Move file to match"])
        ctl = got["controls"]["Move cloud project to match"]
        self.assertTrue(ctl["disabled"], "no site is named like the folder")
        self.assertIn("No cloud site is named", got["html"])

    def test_a_site_spread_over_two_new_folders_is_not_renamed(self):
        """The old folder is gone, but its projects went to two places - no
        single name for the site to take."""
        one = pair("SITE4 Survey", site="SITE4 Quay", site_id="site-4",
                   folder="SITE4 Quay Annex")
        two = pair("SITE4 Design", site="SITE4 Quay", site_id="site-4",
                   folder="SITE4 Quay West")
        got = run({"data": {"matched": [one, two],
                            "siteIds": {"SITE4 Quay": "site-4"}},
                   "row": row_of(one)})
        self.assertNotIn("Rename cloud site to match", got["controls"])
        self.assertIn("Move file to match", got["results"])

    def test_a_folder_named_like_another_site_assigns_the_project_there(self):
        """Renaming onto a name another site already has would leave two
        sites wearing it."""
        p = pair("SITE5 Survey", site="SITE5 Pier", site_id="site-5",
                 folder="SITE5 Jetty")
        got = run({"data": {"matched": [p],
                            "siteIds": {"SITE5 Pier": "site-5",
                                        "SITE5 Jetty": "site-6"}},
                   "row": row_of(p)})
        self.assertNotIn("Rename cloud site to match", got["controls"])
        self.assertEqual([["assign_to_site", "site-6", "SITE5 Survey"]],
                         got["results"]["Move cloud project to match"])

    def test_a_colleagues_project_is_not_offered_the_cloud_move(self):
        p = pair("SITE5 Survey", site="SITE5 Pier", site_id="site-5",
                 folder="SITE5 Jetty", owner=THEM)
        got = run({"data": {"matched": [p],
                            "siteIds": {"SITE5 Pier": "site-5",
                                        "SITE5 Jetty": "site-6"}},
                   "row": row_of(p)})
        self.assertTrue(got["controls"]["Move cloud project to match"]["disabled"])
        self.assertNotIn("Move cloud project to match", got["results"])


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class AgreeingRowsStayQuietTests(unittest.TestCase):

    def test_a_project_in_its_own_sites_folder_has_no_band(self):
        p = pair("SITE7 Survey", site="SITE7 Mole", site_id="site-7",
                 folder="SITE7 Mole")
        got = run({"data": {"matched": [p],
                            "siteIds": {"SITE7 Mole": "site-7"}},
                   "row": row_of(p)})
        self.assertEqual("", got["html"])


if __name__ == "__main__":
    unittest.main()
