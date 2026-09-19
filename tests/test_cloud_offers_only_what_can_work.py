"""A control that exists is a control that works.

"technically we should block all items that are not things that you should be
able to do, or that you can do on a cloud instance anyway, on other people's
files. I don't want the user to be the bug catcher."

Auto-assign proposed three assignments and Ekahau answered `403 Forbidden` to
every one, because the candidate set was gated on the **owner filter** and he
had it on All. A filter is a view, not a permission: All is the right thing to
be on when you want to see everything, and it must not become consent to act
on it.

So the rule this file holds is ownership-shaped but the principle is wider:
where the tool can know in advance that an operation cannot succeed, it does
not offer it, and it says why on the control.

**Which actions need ownership, and which do not**, is the part worth being
explicit about, because refusing too much is its own defect:

* needs it - assign, auto-assign, move to a site, rename, delete, share, and
  replace-cloud, which deletes the old project;
* does not - anything that only reads the cloud or only writes his disk:
  compare, download, link, unlink, and every local-side action.

Driven: the real cell renderers produce the markup, and the controls are read
back out of it.
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
NODE_TIMEOUT_S = 180

PROGRAM = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');

function fakeEl() {
  return {
    innerHTML: '', textContent: '', value: '', checked: false, hidden: false,
    dataset: {}, style: {}, children: [], parentElement: null,
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    addEventListener(){}, removeEventListener(){}, setAttribute(){},
    getAttribute(){ return null; }, removeAttribute(){}, closest(){ return null; },
    querySelector(){ return null; }, querySelectorAll(){ return []; },
    appendChild(){}, remove(){}, focus(){}, click(){}, scrollIntoView(){},
    getBoundingClientRect(){ return { top:0, left:0, width:0, height:0 }; },
  };
}
const sandbox = {
  console, JSON, Math, Date, Map, Set, Promise, RegExp, Intl,
  setTimeout, clearTimeout, setInterval, clearInterval,
  document: {
    getElementById(){ return fakeEl(); }, querySelector(){ return fakeEl(); },
    querySelectorAll(){ return []; }, createElement(){ return fakeEl(); },
    addEventListener(){}, body: fakeEl(), documentElement: fakeEl(),
  },
  navigator: { platform: 'Win32', clipboard: { writeText: async () => {} } },
  location: { href: 'file:///cloud.html', search: '', hash: '' },
  localStorage: { getItem: () => null, setItem(){}, removeItem(){} },
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  alert(){}, confirm(){ return true; }, prompt(){ return null; },
  requestAnimationFrame: (f) => setTimeout(f, 0),
  WD: {
    esc: s => String(s == null ? '' : s).replace(/[&<>"]/g,
      c => ({ '&':'&amp;', '<':'&lt;', '>':'&gt;', '"':'&quot;' }[c])),
    applyVersions(){}, toast(){},
  },
};
sandbox.WD.escAttr = sandbox.WD.esc;
sandbox.WD.escJsStr = s => String(s == null ? '' : s).replace(/['\\]/g, '\\$&');
sandbox.window = sandbox;
vm.createContext(sandbox);
try {
  vm.runInContext(source, sandbox, { filename: 'cloud.js' });
} catch (err) {
  if (!/addEventListener|null|undefined/.test(err.message)) throw err;
}

const ME = 'me@example.invalid';
const THEM = 'colleague@example.invalid';

const mk = (owner) => ({
  status: 'synced', kind: 'projects', matchType: 'id', staleness: null,
  parentSiteId: 's1', parentSiteName: 'Site Alpha',
  cloud: { id: 'p1', name: 'Alpha Survey', owner, unassigned: true,
           sharedWith: [], meta: '2 hr ago' },
  local: { path: 'D:\\E\\Alpha Survey.esx', name: 'Alpha Survey',
           owner, meta: '14 Aug' },
});

vm.runInContext("data = { currentUser: '" + ME + "', matched: [], cloudOnly: [],"
  + " localOnly: [], orphans: { cloudOnly: [] } };"
  + "currentTab = 'projects'; activeFilter = 'all'; setOwnerFilter('all');",
  sandbox);

function controls(owner) {
  sandbox.__row = mk(owner);
  const html = vm.runInContext('cloudCell(__row, new Set())', sandbox);
  const out = {};
  const re = /<button class="row-menu-item([^"]*)"[^>]*>[\s\S]*?<span>([^<]*)<\/span>/g;
  let m;
  while ((m = re.exec(html)) !== null) {
    out[m[2].replace(/[\u2026\u201c\u201d]/g, '').trim()] =
      m[1].indexOf('is-disabled') >= 0 ? 'blocked' : 'live';
  }
  return out;
}

// Replace-cloud, which is a different renderer.
function pushOffered(owner) {
  sandbox.__row = Object.assign(mk(owner), { staleness: 'local_newer' });
  const html = vm.runInContext('stalenessBadgeHtml(__row)', sandbox);
  return {
    live: /pushLocalOverCloud\(/.test(html),
    saysWhy: /Owned by/.test(html),
    offersConfirmPair: /markManualMatch\(/.test(html),
  };
}

// The banner's candidate set.
function autoAssignable(owner) {
  sandbox.__site = [{
    cloud: { id: 's1', name: 'Site Alpha', owner: ME, children: {
      matched: [mk(owner)], cloudOnly: [], localOnly: [] } },
    local: null,
  }];
  return vm.runInContext(
    '_collectAutoAssignable(__site, function () { return true; }).length',
    sandbox);
}

console.log(JSON.stringify({
  mine: controls(ME),
  theirs: controls(THEM),
  pushMine: pushOffered(ME),
  pushTheirs: pushOffered(THEM),
  autoAssignMine: autoAssignable(ME),
  autoAssignTheirs: autoAssignable(THEM),
  defaultOwner: vm.runInContext('defaultOwnerFilter()', sandbox),
}));
"""


def _run() -> dict:
    node = shutil.which("node")
    if not node:  # pragma: no cover
        raise unittest.SkipTest("node is not available")
    r = subprocess.run([node, "-e", PROGRAM, str(CLOUD_JS)],
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError("render failed:\n" + (r.stderr or "")[-3000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


NEEDS_OWNERSHIP = ["Assign to Site Alpha", "Sharing", "Move to a site",
                   "Rename this project", "Delete this project"]
WORKS_ON_ANYONES = ["Check what differs"]


class OnlyOfferWhatCanSucceedTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = _run()

    def test_everything_is_live_on_his_own_project(self):
        """Refusing too much is its own defect."""
        blocked = [k for k, v in self.out["mine"].items() if v == "blocked"]
        self.assertEqual([], blocked, f"refused on his own project: {blocked}")

    def test_the_cloud_writes_are_refused_on_someone_elses(self):
        theirs = self.out["theirs"]
        still_live = [c for c in NEEDS_OWNERSHIP
                      if theirs.get(c) == "live"]
        self.assertEqual(
            [], still_live,
            f"offered on a project he does not own: {still_live}. Ekahau "
            f"answers 403 to each of these.")

    def test_reading_someone_elses_project_is_still_allowed(self):
        """Being shared a project is permission to read it. A comparison
        downloads a copy and changes nothing, so blocking it would be the
        guard firing on a case that works."""
        theirs = self.out["theirs"]
        for c in WORKS_ON_ANYONES:
            self.assertEqual("live", theirs.get(c),
                             f"{c} was refused, and it does not need ownership")

    def test_replace_cloud_is_refused_and_says_why(self):
        """It deletes the old project, so it needs ownership - and the reason
        shown has to be the real one. The refusal path here already existed
        for a guessed pairing and offered `Confirm this pair`, which does
        nothing about ownership and would send him round to the same 403."""
        self.assertTrue(self.out["pushMine"]["live"], "refused on his own")
        theirs = self.out["pushTheirs"]
        self.assertFalse(theirs["live"], "offered on someone else's project")
        self.assertTrue(theirs["saysWhy"], "refused without giving the reason")
        self.assertFalse(theirs["offersConfirmPair"],
                         "offered a remedy that does not apply")

    def test_auto_assign_proposes_only_projects_he_owns(self):
        """The reported failure: three proposed, three 403s. The candidate set
        was gated on the owner filter, and he was on All."""
        self.assertEqual(1, self.out["autoAssignMine"])
        self.assertEqual(
            0, self.out["autoAssignTheirs"],
            "auto-assign proposed a project he does not own; Ekahau refuses "
            "these with 403")


class TheListOpensOnHisOwnWorkTests(unittest.TestCase):
    """"the default for this whole entire thing should always be the user's
    files... I've hated it - that's why I always hit it on Mine."

    It is also the safer default, which is what settles it: on All the list
    carries colleagues' projects, and that is the state in which an offered
    action can be refused by Ekahau.
    """

    def test_the_client_default_is_mine(self):
        self.assertEqual("mine", _run()["defaultOwner"])

    def test_the_shipped_setting_agrees_with_the_client(self):
        """These disagreeing means a flash of everyone's projects on load,
        before the settings call comes back."""
        from tools import settings as st
        self.assertEqual("mine",
                         st.DEFAULTS["cloud"]["default_owner_filter"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
