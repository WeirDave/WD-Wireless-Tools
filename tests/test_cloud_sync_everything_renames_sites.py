"""Sync everything sends a folder's new name up to its cloud site.

"If you rename the folder in explorer or in finder and then you go back into
the program it's renamed - you can see that it is and it spots the
differences - but you can't upload to the cloud."

`syncEverythingPlan` walked every pair and skipped folders outright ("a site
is a folder, not a file"), and nothing else in it looked at a site's name. So
after a rename the big Sync button reported "Local and cloud already match",
with the cloud site still wearing its old name.

Driven end to end: the real `syncEverything` builds its dialog, the stubbed
confirm presses OK, the ticks are read back off the checkboxes the dialog
actually rendered, and what is asserted is the call that reaches the server.
Every name here is invented.
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

PROGRAM = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const listeners = {};
function fakeEl(id) {
  return { id, innerHTML: '', textContent: '', value: '', checked: false,
    hidden: false, disabled: false, dataset: {}, style: {}, children: [],
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    addEventListener(ev, fn){ listeners[id + ':' + ev] = fn; },
    removeEventListener(){}, setAttribute(){}, getAttribute(){ return null; },
    querySelector(){ return null; }, querySelectorAll(){ return []; },
    appendChild(){}, remove(){}, focus(){}, click(){} };
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

const input = JSON.parse(process.argv[2]);
sandbox.__data = Object.assign({currentUser: 'me@example.invalid', matched: [],
  cloudOnly: [], localOnly: [], orphans: {cloudOnly: [], localOnly: []},
  summary: {}}, input.data);
vm.runInContext("data = __data; currentTab = 'sites';", sandbox);

const calls = [], toasts = [];
let body = null;
sandbox.pyApi = async (...args) => { calls.push(args); return { ok: true }; };
sandbox.opEnqueue = (spec) => ({ promise: Promise.resolve(spec.run('op-1')) });
sandbox._scheduleOpRefresh = () => {};
sandbox._reportSyncOutcome = () => {};
sandbox.clearSelection = () => {};
sandbox.toast = (msg) => { toasts.push(msg); };
sandbox._syncPickUpdate = () => {};
sandbox.showConfirmModal = async (title, html) => {
  body = html;
  const ok = listeners['confirmActionOkBtn:click'];
  if (ok) ok();
  return true;
};
//: The ticks, read off the rendered dialog - the same markup he would see.
sandbox._syncPicked = (kind) => {
  const out = [];
  const re = /<input type="checkbox" class="sync-pick"([^>]*)>/g;
  let m;
  while ((m = re.exec(body || ''))) {
    const attrs = m[1];
    if (!new RegExp('data-kind="' + kind + '"').test(attrs)) continue;
    if (!/ checked/.test(attrs)) continue;
    out.push(Number((attrs.match(/data-idx="(\d+)"/) || [])[1]));
  }
  return out;
};

(async () => {
  const plan = vm.runInContext('syncEverythingPlan()', sandbox);
  await vm.runInContext('syncEverything()', sandbox);
  process.stdout.write(JSON.stringify({
    renames: plan.siteRenames, calls, toasts, body }));
})().catch(err => { console.error(err.stack || err.message); process.exit(1); });
"""


def run(data):
    r = subprocess.run(
        ["node", "-e", PROGRAM, str(CLOUD_JS), json.dumps({"data": data})],
        capture_output=True, text=True, encoding="utf-8",
        timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip()[-2500:])
    return json.loads(r.stdout.strip().splitlines()[-1])


def site_pair(sid, cloud_name, folder_name, match_type="code"):
    return {"cloud": {"id": sid, "name": cloud_name,
                      "children": {"matched": [], "cloudOnly": [],
                                   "localOnly": []}},
            "local": {"path": "D:/Esx/" + folder_name, "name": folder_name,
                      "isDir": True},
            "matchType": match_type,
            "namesDiffer": cloud_name.strip() != folder_name.strip()}


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class ARenamedFolderGoesUpTests(unittest.TestCase):

    def test_the_cloud_site_takes_the_folders_new_name(self):
        got = run({"matched": [site_pair("site-3", "SITE3 Dockside",
                                         "SITE3 Dockside North")]})
        self.assertEqual(
            [["rename_cloud", "sites", "site-3", "SITE3 Dockside North"]],
            got["calls"])

    def test_the_dialog_shows_both_names(self):
        got = run({"matched": [site_pair("site-3", "SITE3 Dockside",
                                         "SITE3 Dockside North")]})
        self.assertIn("SITE3 Dockside</td>", got["body"])
        self.assertIn("SITE3 Dockside North</td>", got["body"])
        self.assertIn("cloud site", got["body"])

    def test_it_no_longer_says_everything_already_matches(self):
        got = run({"matched": [site_pair("site-3", "SITE3 Dockside",
                                         "SITE3 Dockside North")]})
        self.assertFalse(any("already match" in t for t in got["toasts"]),
                         got["toasts"])


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class OnlyWhatDiffersAndCanBeCheckedTests(unittest.TestCase):

    def test_a_site_paired_on_wording_alone_arrives_unticked(self):
        got = run({"matched": [site_pair("site-4", "SITE4 Quay",
                                         "Harbour Quay Annex", "fuzzy")]})
        self.assertEqual(1, len(got["renames"]))
        self.assertEqual([], got["calls"])
        self.assertIn("similar wording", got["body"])

    def test_a_site_whose_name_already_agrees_is_left_alone(self):
        got = run({"matched": [site_pair("site-5", "SITE5 Pier",
                                         "SITE5 Pier", "exact")]})
        self.assertEqual([], got["renames"])
        self.assertEqual([], got["calls"])

    def test_a_project_file_is_not_mistaken_for_a_site(self):
        pair = {"cloud": {"id": "p-1", "name": "SITE7 Old"},
                "local": {"path": "D:/Esx/SITE7/SITE7 New.esx",
                          "name": "SITE7 New", "isDir": False},
                "matchType": "id", "namesDiffer": True}
        got = run({"matched": [pair]})
        self.assertEqual([], got["renames"])
        self.assertFalse(any(c[0] == "rename_cloud" for c in got["calls"]))


if __name__ == "__main__":
    unittest.main()
