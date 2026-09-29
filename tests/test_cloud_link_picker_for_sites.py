"""A folder and a cloud site that no longer pair can be linked by hand.

"add the link picker for unpaired sites too."

A folder renamed far enough in Explorer or Finder stops pairing with its cloud
site at all - no shared site code, not enough words in common - and the two sat
on the Tree as "Local folder only" and "Cloud site only". The only offer was
"+ Cloud site", which makes a second site. The link picker existed, but only
for projects.

Now the folder's row carries **Link to a cloud site…**, the cloud site's row
menu carries **Link to a local folder…**, and the picker lists only unpaired
sites or folders. What it files is an ordinary manual match, which the site
matcher already honours - so the pair then gets the rename band and the Sync
everything rename like any other.

The same pass fixes the project picker on the Tree tab, which read the top-level
lists as projects: on that tab they are sites and folders, so whole sites were
offered as a project's counterpart.

Driven through the real renderer, the real picker and the real pick handler,
against a recording `pyApi`. Every name here is invented.
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
const els = {};
function fakeEl(id) {
  if (id && els[id]) return els[id];
  const el = { id, innerHTML: '', textContent: '', value: '', checked: false,
    hidden: false, disabled: false, dataset: {}, style: {}, children: [],
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    addEventListener(){}, removeEventListener(){}, setAttribute(){},
    getAttribute(){ return null; },
    querySelector(){ return null; }, querySelectorAll(){ return []; },
    appendChild(){}, remove(){}, focus(){}, click(){} };
  if (id) els[id] = el;
  return el;
}
const sandbox = {
  console, JSON, Math, Date, Map, Set, Promise, RegExp, Intl,
  setTimeout, clearTimeout, setInterval, clearInterval,
  document: { getElementById(id){ return fakeEl(id); },
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

const input = JSON.parse(process.argv[2]);
sandbox.__data = Object.assign({currentUser: 'me@example.invalid', matched: [],
  cloudOnly: [], localOnly: [], orphans: {cloudOnly: [], localOnly: []}}, input.data);
vm.runInContext("data = __data; currentTab = " + JSON.stringify(input.tab || 'sites')
  + "; activeFilter = 'all';", sandbox);

const calls = [];
sandbox.pyApi = async (...args) => { calls.push(args); return { ok: true }; };
sandbox.refreshData = () => {};
sandbox.showModal = () => {};
sandbox.closeModal = () => {};
sandbox.toast = () => {};

function pickerItems() {
  const html = els.linkPickerList ? els.linkPickerList.innerHTML : '';
  const out = [];
  const re = /<div class="lp-item[^"]*"[^>]*data-fn="_lpPick"[^>]*>/g;
  let m;
  while ((m = re.exec(html))) {
    const tag = m[0];
    const at = (n) => _unattr((tag.match(new RegExp(n + '="([^"]*)"')) || [])[1] || '');
    out.push({ arg: at('data-arg'), name: at('data-arg2') });
  }
  return out;
}

(async () => {
  const out = {};
  if (input.row) {
    sandbox.__row = input.row;
    out.band = vm.runInContext('rowDetailHtml(__row, 0)', sandbox);
    out.cloudCell = input.row.cloud ? vm.runInContext('cloudCell(__row, new Set())', sandbox) : '';
    out.localCell = input.row.local ? vm.runInContext('localCell(__row, new Set())', sandbox) : '';
    const hit = delegated(out.band + out.cloudCell + out.localCell, 'openLinkPicker');
    out.opener = hit ? hit.args : null;
    if (hit) {
      sandbox.openLinkPicker.apply(null, hit.args);
      out.title = els.linkPickerTitle && els.linkPickerTitle.textContent;
      out.items = pickerItems();
      if (out.items.length) {
        calls.length = 0;
        sandbox._lpPick(out.items[0].arg, out.items[0].name);
        await new Promise(r => setTimeout(r, 0));
        out.calls = calls.slice();
      }
    }
  }
  if (input.open) {
    sandbox.openLinkPicker.apply(null, input.open);
    out.items = pickerItems();
  }
  process.stdout.write(JSON.stringify(out));
})().catch(err => { console.error(err.stack || err.message); process.exit(1); });
"""


def run(payload):
    r = subprocess.run(
        ["node", "-e", PROGRAM, str(CLOUD_JS), json.dumps(payload)],
        capture_output=True, text=True, encoding="utf-8",
        timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip()[-2500:])
    return json.loads(r.stdout.strip().splitlines()[-1])


FOLDER = {"path": "D:/Esx/Harbour Pier East", "name": "Harbour Pier East",
          "isDir": True, "meta": "2 esx",
          "children": {"matched": [], "cloudOnly": [],
                       "localOnly": [{"path": "D:/Esx/Harbour Pier East/Survey.esx",
                                      "name": "Survey"}]}}
SITE = {"id": "site-9", "name": "SITE9 Quayside", "meta": "2 esx",
        "children": {"matched": [], "localOnly": [],
                     "cloudOnly": [{"id": "proj-9", "name": "SITE9 Survey"}]}}
UNPAIRED = {"cloudOnly": [SITE], "localOnly": [FOLDER]}


def folder_row():
    return {"kind": "sites", "status": "orphan", "cloud": None, "local": FOLDER,
            "key": "l:" + FOLDER["path"]}


def site_row():
    return {"kind": "sites", "status": "orphan", "cloud": SITE, "local": None,
            "key": "c:" + SITE["id"]}


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class AnUnpairedFolderCanBeLinkedToItsSiteTests(unittest.TestCase):

    def test_the_folder_row_offers_the_link_and_it_lists_the_unpaired_site(self):
        got = run({"data": UNPAIRED, "row": folder_row()})
        self.assertIn("Link to a cloud site…", got["band"])
        self.assertEqual("Link to a cloud site", got["title"])
        self.assertEqual([{"arg": "site-9", "name": "SITE9 Quayside"}],
                         got["items"])

    def test_picking_the_site_files_a_manual_match_of_site_and_folder(self):
        got = run({"data": UNPAIRED, "row": folder_row()})
        self.assertEqual(
            [["mark_manual_match", "site-9", "D:/Esx/Harbour Pier East",
              "SITE9 Quayside", "Harbour Pier East"]],
            got["calls"])

    def test_a_cloud_site_only_row_links_from_its_menu_to_the_folder(self):
        got = run({"data": UNPAIRED, "row": site_row()})
        self.assertEqual("", got["band"], "no band on cloud-only sites")
        self.assertIn("Link to a local folder…", got["cloudCell"])
        self.assertEqual([{"arg": "D:/Esx/Harbour Pier East",
                           "name": "Harbour Pier East"}], got["items"])
        self.assertEqual(
            [["mark_manual_match", "site-9", "D:/Esx/Harbour Pier East",
              "SITE9 Quayside", "Harbour Pier East"]],
            got["calls"])

    def test_a_folder_with_nothing_to_link_to_has_no_band(self):
        got = run({"data": {"cloudOnly": [], "localOnly": [FOLDER]},
                   "row": folder_row()})
        self.assertEqual("", got["band"])
        self.assertIn("Link to a cloud site…", got["localCell"],
                      "the menu item stays, so it can be found")


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class TheProjectPickerOnTheTreeListsProjectsTests(unittest.TestCase):

    def test_a_local_project_is_offered_cloud_projects_not_sites(self):
        got = run({"data": UNPAIRED,
                   "open": ["local", "D:/Esx/Harbour Pier East/Survey.esx",
                            "Survey"]})
        args = [i["arg"] for i in got["items"]]
        self.assertIn("proj-9", args)
        self.assertNotIn("site-9", args)

    def test_a_cloud_project_is_offered_local_files_not_folders(self):
        got = run({"data": UNPAIRED,
                   "open": ["cloud", "proj-9", "SITE9 Survey"]})
        args = [i["arg"] for i in got["items"]]
        self.assertIn("D:/Esx/Harbour Pier East/Survey.esx", args)
        self.assertNotIn("D:/Esx/Harbour Pier East", args)


class TheSiteMatcherHonoursTheLinkTests(unittest.TestCase):
    """The picker files a manual match; this is the half that makes it count."""

    def test_a_linked_site_and_folder_pair_as_a_manual_match(self):
        from tools import cloud_manager as CM
        cloud = [{"id": "site-9", "name": "SITE9 Quayside", "code": "SITE9"}]
        local = [{"path": "D:/Esx/Harbour Pier East", "name": "Harbour Pier East",
                  "code": "", "isDir": True}]
        unlinked = CM.build_matches(cloud, local)
        self.assertEqual([], unlinked["matched"], "the fixture must be unpaired")
        linked = CM.build_matches(
            cloud, local, manual_map={"site-9": "d:/esx/harbour pier east"})
        self.assertEqual(1, len(linked["matched"]))
        self.assertEqual("manual", linked["matched"][0]["matchType"])
        self.assertTrue(linked["matched"][0]["namesDiffer"])


if __name__ == "__main__":
    unittest.main()
