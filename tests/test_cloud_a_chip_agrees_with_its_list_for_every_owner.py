"""Every chip's number is the rows that chip draws — under every owner filter.

"I clicked cloud only at the top and it says there's three items, and when I
click it there's only two ESX files showing. Then I click local only, which
also has a three, and quite literally nothing shows."

`tests/test_cloud_a_count_matches_its_list.py` already asks this question and
passes, because its harness hardcodes `ownerFilter()` to `'all'` — the one
setting under which the two agree. The counter walks a site's children with no
owner test at all, while `renderTreeChildren` filters them; so on `Mine`, a
colleague's project inside one of his sites is counted and not drawn.

Two separate ways for a number to be unreconcilable, and this file holds both:

* **the owner filter** — the counts and the rows must be computed over the
  same set, whichever owner filter is on;
* **the unit** — "sites should not be counted in those... we should only be
  concerned with projects, and site names should not be considered projects."
  A project-level chip counts projects. Only `Unmatched sites` counts sites,
  and it says so in its name.

The comparison is against the **real** `renderLedger`, not a re-implementation
of the filter: the count is read from what `updateDashboard` writes, the rows
are counted in the markup the list produced, and nothing in between is
restated. A test that rebuilt `pass()` would agree with itself.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 180

#: chip element id -> the filter it applies. Project-level chips only; the
#: site-level one is asserted separately because it is deliberately different.
PROJECT_CHIPS = {
    "dCloudOnly": "orphans-cloud",
    "dLocalOnly": "orphans-local",
    "dMismatches": "mismatches",
    "dNameMatches": "name-matches",
    "dExternal": "external",
    "dUnshared": "unshared",
    "dStale": "stale",
}

PROGRAM = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const OWN = process.argv[2];

const counts = {};
function fakeEl(id) {
  const el = {
    id: id || '', innerHTML: '', value: '', checked: false, hidden: false,
    dataset: {}, style: {}, children: [], parentElement: null,
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    addEventListener(){}, removeEventListener(){}, setAttribute(){},
    getAttribute(){ return null; }, removeAttribute(){}, closest(){ return null; },
    querySelector(){ return null; }, querySelectorAll(){ return []; },
    appendChild(){}, remove(){}, focus(){}, click(){}, scrollIntoView(){},
    getBoundingClientRect(){ return { top:0, left:0, width:0, height:0 }; },
  };
  let text = '-';
  Object.defineProperty(el, 'textContent', {
    get: () => text,
    set: (v) => { text = String(v); if (id) counts[id] = String(v); },
  });
  return el;
}
const byId = new Map();
const sandbox = {
  console, JSON, Math, Date, Map, Set, Promise, RegExp, Intl,
  setTimeout, clearTimeout, setInterval, clearInterval,
  document: {
    getElementById(id) {
      if (!byId.has(id)) byId.set(id, fakeEl(id));
      return byId.get(id);
    },
    querySelector(){ return fakeEl(); },
    querySelectorAll(){ return []; },
    createElement(){ return fakeEl(); },
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

// -------------------------------------------------- his shape, mixed owners
const ME = 'me@example.invalid';
const THEM = 'colleague@example.invalid';

const proj = (id, name, o) => Object.assign({
  id, name, owner: ME, hasSite: true, meta: '2 hr ago', sharedWith: [],
  projectType: 'Design',
}, o || {});
const file = (name, o) => Object.assign({
  name, path: 'D:\\E\\' + name + '.esx', meta: '14 Aug', owner: ME,
}, o || {});
const pair = (id, name, o) => Object.assign({
  cloud: proj(id, name, (o || {}).cloud), local: file(name, (o || {}).local),
  matchType: 'id', staleness: null, namesDiffer: false, differenceKind: null,
}, (o || {}).pair || {});

// One site of his, holding one of his projects and one of a colleague's -
// plus a colleague-owned loose file. This is the mix that makes a count
// disagree with a list the moment the owner filter is anything but All.
const kidsA = {
  matched: [
    pair('p1', 'Alpha Survey'),
    pair('p2', 'Bravo Survey', { cloud: { owner: THEM }, local: { owner: THEM } }),
  ],
  cloudOnly: [proj('c1', 'Charlie Cloud Only'),
              proj('c2', 'Delta Cloud Only', { owner: THEM })],
  localOnly: [file('Echo Local Only'),
              file('Foxtrot Local Only', { owner: THEM })],
  heldBack: [],
};
const kidsB = {
  matched: [pair('p3', 'Golf Survey', { pair: { namesDiffer: true },
                                        local: { name: 'Golf Survey Old' } }),
            pair('p4', 'Hotel Survey', { pair: { matchType: 'exact',
                                                 staleness: 'cloud_newer' } })],
  cloudOnly: [], localOnly: [], heldBack: [],
};

const site = (id, name, kids, o) => Object.assign({
  id, name, owner: ME, hasSite: true, meta: '2 hr ago', sharedWith: [],
  children: kids,
}, o || {});

const fixture = {
  currentUser: ME,
  summary: { matched: 2 },
  matched: [
    { cloud: site('s1', 'Site Alpha', kidsA),
      local: file('Site Alpha', { isDir: true, children: kidsA }),
      matchType: 'exact', namesDiffer: false, staleness: null },
    { cloud: site('s2', 'Site Bravo', kidsB),
      local: file('Site Bravo', { isDir: true, children: kidsB }),
      matchType: 'exact', namesDiffer: false, staleness: null },
  ],
  cloudOnly: [],
  localOnly: [],
  orphans: { cloudOnly: [proj('u1', 'Unassigned One', { unassigned: true }),
                         proj('u2', 'Unassigned Two', { unassigned: true,
                                                        owner: THEM })] },
};

vm.runInContext('data = ' + JSON.stringify(fixture) + ';'
  + "currentTab = 'sites'; activeLetter = ''; collapsed = new Set();"
  + "setOwnerFilter('" + OWN + "');", sandbox);

// -------------------------------------------- what each chip says, and draws
const FILTERS = {
  dCloudOnly: 'orphans-cloud', dLocalOnly: 'orphans-local',
  dMismatches: 'mismatches', dNameMatches: 'name-matches',
  dExternal: 'external', dUnshared: 'unshared', dStale: 'stale',
  dUnmatchedSites: 'unmatched-sites', dAll: 'all',
};

const out = {};
for (const [id, filter] of Object.entries(FILTERS)) {
  vm.runInContext("activeFilter = '" + filter + "'; updateDashboard();", sandbox);
  const said = counts[id];
  const html = vm.runInContext('renderLedger(function () { return true; })', sandbox);
  // Project rows carry `tree-child`; site rows do not. Count them apart.
  const projectRows = (html.match(/<div class="ledger-row tree-child /g) || []).length;
  const orphanBlock = html.indexOf('tree-orphan-head');
  const unassignedRows = orphanBlock < 0 ? 0
    : (html.slice(orphanBlock).match(/<div class="ledger-row orphan/g) || []).length;
  const siteRows = (html.match(/<div class="ledger-row (?!tree-child|orphan)/g) || []).length;
  const emptyNotes = (html.match(/No projects here match this filter\./g) || []).length;
  out[id] = {
    filter, said,
    projectRows: projectRows + unassignedRows,
    siteRows, emptyNotes,
  };
}

/* A filter nothing answers. No fixture project is Hybrid, so this is
   guaranteed empty and is the shape of "0 not assigned" on his screen. */
vm.runInContext("activeFilter = 'type-hybrid'; updateDashboard();", sandbox);
const emptyHtml = vm.runInContext('renderLedger(function () { return true; })', sandbox);
out._empty = {
  filter: 'type-hybrid',
  projectRows: (emptyHtml.match(/<div class="ledger-row tree-child /g) || []).length,
  siteRows: (emptyHtml.match(/<div class="ledger-row (?!tree-child|orphan)/g) || []).length,
  perSiteNotes: (emptyHtml.match(/No projects here match this filter\./g) || []).length,
  emptyStates: (emptyHtml.match(/class="empty-msg/g) || []).length,
};

console.log(JSON.stringify(out));
"""


def _run(owner: str) -> dict:
    node = shutil.which("node")
    if not node:  # pragma: no cover
        raise unittest.SkipTest("node is not available")
    r = subprocess.run([node, "-e", PROGRAM, str(CLOUD_JS), owner],
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError("render failed:\n" + (r.stderr or "")[-3000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


class AChipAgreesWithItsListTests(unittest.TestCase):

    def _check_owner(self, owner: str) -> None:
        got = _run(owner)
        wrong = []
        for chip, filt in PROJECT_CHIPS.items():
            row = got[chip]
            if str(row["said"]) != str(row["projectRows"]):
                wrong.append(
                    f"{filt}: chip says {row['said']}, list draws "
                    f"{row['projectRows']} project row(s)")
        self.assertEqual([], wrong, f"owner={owner}\n  " + "\n  ".join(wrong))

    def test_the_chips_agree_with_the_list_when_showing_everyone(self):
        self._check_owner("all")

    def test_the_chips_agree_with_the_list_when_showing_only_mine(self):
        """The reported case. The counter walks a site's children with no
        owner test; the list filters them. On Mine, a colleague's project
        inside one of his sites is counted and never drawn."""
        self._check_owner("mine")

    def test_the_chips_agree_with_the_list_when_showing_only_others(self):
        self._check_owner("others")


class AProjectChipCountsProjectsTests(unittest.TestCase):
    """"site names should not be considered projects. That doesn't make any
    sense." The unit of work is the project; a site is how projects are
    organised. A chip that silently adds sites to projects produces a number
    nothing on screen adds up to."""

    def test_external_counts_projects_rather_than_the_sites_holding_them(self):
        got = _run("all")
        row = got["dExternal"]
        self.assertEqual(
            str(row["projectRows"]), str(row["said"]),
            f"External says {row['said']} over {row['projectRows']} project "
            f"row(s) and {row['siteRows']} site row(s) - it is counting sites",
        )

    def test_unmatched_sites_is_the_only_chip_that_counts_sites(self):
        """And it says so in its name, which is what makes it allowed."""
        got = _run("all")
        row = got["dUnmatchedSites"]
        self.assertEqual(str(row["siteRows"]), str(row["said"]),
                         f"unmatched-sites says {row['said']} over "
                         f"{row['siteRows']} site row(s)")


class AnEmptyFilterShowsOneEmptyStateTests(unittest.TestCase):
    """"if we click on a filter that has nothing in it, normally we just say
    there's nothing in it."

    A filter matching nothing drew the site scaffolding anyway - three site
    rows reading `0 of 3 files`, each followed by "No projects here match this
    filter." Three rows and three apologies where one sentence was wanted.
    """

    def test_a_filter_with_no_matching_projects_draws_no_site_rows(self):
        got = _run("all")["_empty"]
        self.assertEqual(0, got["projectRows"], "the filter should match nothing")
        self.assertEqual(
            0, got["siteRows"],
            f"drew {got['siteRows']} site row(s) for a filter nothing matches")
        self.assertEqual(
            0, got["perSiteNotes"],
            f"drew {got['perSiteNotes']} per-site 'nothing matches' notices "
            f"instead of one empty state")

    def test_it_says_once_that_there_is_nothing(self):
        got = _run("all")["_empty"]
        self.assertEqual(1, got["emptyStates"],
                         "a filter matching nothing should say so, once")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
