"""Both lists are in order, say each thing once, and have no empty sections.

"the flat view was a total mess - I went in there, it wasn't in alphabetical
order, the rows were just a mess in how they were laid out, there was
repetition, it was a hot mess."

Three separate claims, and they are checked separately here rather than argued
about. The list is rendered by the **real** `renderLedger` - Flat and Tree
both - against a list the size of his: 98 sites, 18 of them with a local
folder. A ten-row fixture answers none of these questions, because all three
failures are about what a long list does.

The one that was still true is the third. Every letter A-Z got a section band
whether or not it had anything under it, so the number of bands was fixed at 27
no matter how few letters were in use. Site codes cluster on a handful of first
letters, so his real list opened on several empty bands before its first row
and scattered the rest through the middle - and the A-Z jump bar, which is the
thing that genuinely answers "which letters do I have", deliberately ignored
them when working out which letters exist. They were length without
information, and at his density they are most of what the eye sees.

So the assertion is not "the placeholders are gone", which would pass with the
whole list deleted. It is **every band has rows under it, the rows are in
order, and no row appears twice** - properties of the rendered list that stay
true whatever the implementation does next.
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

# `CLUSTER` is how many distinct first letters the invented site codes use.
# 26 spreads them; 3 is the shape a real naming scheme has, and is the case
# that produced two dozen empty bands.
PROGRAM = r"""
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync(process.argv[1], 'utf8');
const CLUSTER = parseInt(process.argv[2], 10);
const TAB = process.argv[3];

// The thinnest browser that lets the file finish loading. Nothing here is
// under test; the render functions are.
function fakeEl() {
  return {
    innerHTML: '', textContent: '', value: '', checked: false, hidden: false,
    dataset: {}, style: {},
    classList: { add(){}, remove(){}, toggle(){}, contains(){ return false; } },
    addEventListener(){}, removeEventListener(){}, setAttribute(){},
    getAttribute(){ return null; }, removeAttribute(){}, closest(){ return null; },
    querySelector(){ return null; }, querySelectorAll(){ return []; },
    appendChild(){}, remove(){}, focus(){}, click(){}, scrollIntoView(){},
    getBoundingClientRect(){ return { top: 0, left: 0, width: 0, height: 0 }; },
    children: [], parentElement: null, offsetWidth: 0, offsetHeight: 0,
  };
}
const sandbox = {
  console, JSON, Math, Date, Map, Set, Promise, RegExp, Intl,
  setTimeout, clearTimeout, setInterval, clearInterval,
  document: {
    getElementById(){ return fakeEl(); },
    querySelector(){ return fakeEl(); },
    querySelectorAll(){ return []; },
    createElement(){ return fakeEl(); },
    addEventListener(){},
    body: fakeEl(), documentElement: fakeEl(),
  },
  navigator: { platform: 'Win32', clipboard: { writeText: async () => {} } },
  location: { href: 'file:///cloud.html', search: '', hash: '' },
  localStorage: { getItem: () => null, setItem(){}, removeItem(){} },
  fetch: async () => ({ ok: true, json: async () => ({}) }),
  alert(){}, confirm(){ return true; }, prompt(){ return null; },
  requestAnimationFrame: (f) => setTimeout(f, 0),
  WD: {
    esc: s => String(s == null ? '' : s).replace(/[&<>"]/g,
      c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])),
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
  // Page wiring at the foot of the file wants a real document. A throw there
  // must not hide the render, which is what is being asked about.
  if (!/addEventListener|null|undefined/.test(err.message)) throw err;
}

// --------------------------------------------------- a list the size of his
const OWNER = 'survey.lead@example.invalid';
const PLACES = ['Riverside Block', 'North Campus', 'Alpha Warehouse',
                'Bravo Logistics', 'South Admin'];
const WORK = ['Level 2 Remediation Survey', 'Phase 3', 'Cold Store',
              'Roof Plant and Antenna Runs'];

const sites = [];
for (let i = 0; i < 98; i++) {
  const letter = String.fromCharCode(65 + (i % CLUSTER));
  sites.push(letter + (100 + i) + ' ' + PLACES[i % PLACES.length]);
}

// Projects, for the Flat list: a cloud project paired straight to its .esx.
const matched = [], cloudOnly = [], localOnly = [];
let n = 0;
sites.forEach((site, i) => {
  const hasFolder = i < 18;
  for (let k = 0; k < (hasFolder ? 4 : 2); k++) {
    n++;
    const name = site + ' - ' + WORK[k % WORK.length];
    const cloud = {
      id: 'c' + n, name, owner: OWNER, hasSite: true, meta: '2 hr ago',
      projectType: ['Design', 'Measured', 'Hybrid'][n % 3],
      siteName: site, siteId: 's' + i, sharedWith: [],
    };
    if (hasFolder) {
      matched.push({
        cloud,
        local: { path: 'D:\\Ekahau\\' + site + '\\' + name + '.esx', name,
                 folder: site, meta: '14 Aug', projectType: cloud.projectType },
        matchType: (n % 4) ? 'id' : 'exact',
        staleness: (n % 7 === 0) ? 'cloud_newer' : null,
        namesDiffer: (n % 11 === 0),
      });
    } else {
      cloudOnly.push(cloud);
    }
  }
});
for (let i = 0; i < 6; i++) {
  const name = sites[i] + ' - Loose ' + i;
  localOnly.push({ path: 'D:\\Ekahau\\' + sites[i] + '\\' + name + '.esx',
                   name, folder: sites[i], meta: '14 Aug' });
}

// Sites, for the Tree: the same projects, nested under their site.
const kidsOf = (site) => {
  const mine = matched.filter(p => p.cloud.siteName === site);
  const theirs = cloudOnly.filter(c => c.siteName === site);
  const loose = localOnly.filter(l => l.folder === site);
  return { matched: mine, cloudOnly: theirs, localOnly: loose };
};
const siteMatched = [], siteCloudOnly = [];
sites.forEach((site, i) => {
  const children = kidsOf(site);
  const cloud = { id: 's' + i, name: site, owner: OWNER, hasSite: true,
                  meta: '2 hr ago', children, sharedWith: [] };
  if (i < 18) {
    siteMatched.push({
      cloud,
      local: { path: 'D:\\Ekahau\\' + site, name: site, isDir: true,
               meta: '14 Aug', children },
      matchType: 'id', staleness: null, namesDiffer: false,
    });
  } else {
    siteCloudOnly.push(cloud);
  }
});

const fixture = (TAB === 'sites')
  ? { currentUser: OWNER, summary: { matched: siteMatched.length },
      matched: siteMatched, cloudOnly: siteCloudOnly, localOnly: [],
      orphans: { cloudOnly: [], localOnly: [] } }
  : { currentUser: OWNER, summary: { matched: matched.length },
      matched, cloudOnly, localOnly,
      orphans: { cloudOnly: [], localOnly: [] } };

/* `data`, `currentTab` and `activeFilter` are `let` bindings inside the
   script rather than properties of the global object, so they are assigned
   in the context. */
vm.runInContext(
  'data = ' + JSON.stringify(fixture) + ';'
  + "currentTab = '" + TAB + "'; activeFilter = 'all'; activeLetter = '';"
  + 'collapsed = new Set();',
  sandbox);

const html = vm.runInContext('renderLedger(function () { return true; })', sandbox);

// ------------------------------------------- read the list back in page order
const strip = (s) => s.replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&')
                      .replace(/\s+/g, ' ').trim();
const marks = [];
const tok = /<div class="(ledger-group-head[^"]*|ledger-row [^"]*)"[^>]*>/g;
let m;
while ((m = tok.exec(html)) !== null) marks.push({ cls: m[1], at: m.index, end: tok.lastIndex });

/* On Tree a site's projects are rows too, carrying `tree-child`. They are
   their own ordered list inside each site, so they are read as a separate
   level rather than counted against the sites. */
const seq = [];
marks.forEach((mk, i) => {
  const chunk = html.slice(mk.end, i + 1 < marks.length ? marks[i + 1].at : html.length);
  if (mk.cls.indexOf('ledger-group-head') === 0) {
    seq.push({ kind: 'band', letter: strip(chunk).charAt(0) });
  } else {
    const c = /<span class="cell-name"[^>]*>([\s\S]*?)<\/span>/.exec(chunk);
    seq.push({ kind: mk.cls.indexOf('tree-child') >= 0 ? 'child' : 'row',
               name: c ? strip(c[1]) : '' });
  }
});

// A band with no top-level row before the next band is an empty section.
const emptyBands = [];
seq.forEach((x, i) => {
  if (x.kind !== 'band') return;
  let j = i + 1;
  while (j < seq.length && seq[j].kind === 'child') j++;
  if (j >= seq.length || seq[j].kind === 'band') emptyBands.push(x.letter);
});

const inOrder = (names) => {
  const sorted = names.slice()
    .sort((x, y) => x.localeCompare(y, undefined, { sensitivity: 'base' }));
  return names.findIndex((v, i) => v !== sorted[i]);
};
const repeats = (names) => {
  const counts = new Map();
  names.forEach(nm => counts.set(nm, (counts.get(nm) || 0) + 1));
  return [...counts.entries()].filter(([, c]) => c > 1).map(([nm]) => nm);
};

const rowNames = seq.filter(x => x.kind === 'row').map(x => x.name);
const outOfOrderAt = inOrder(rowNames);

// Each site's own run of children, read as its own list.
const runs = [];
let run = null;
seq.forEach(x => {
  if (x.kind === 'child') { (run = run || []).push(x.name); }
  else if (run) { runs.push(run); run = null; }
});
if (run) runs.push(run);
const childOutOfOrder = runs.filter(rn => inOrder(rn) !== -1).length;
const childRepeats = runs.reduce((acc, rn) => acc.concat(repeats(rn)), []);

const expected = (TAB === 'sites')
  ? siteMatched.length + siteCloudOnly.length
  : matched.length + cloudOnly.length + localOnly.length;

console.log(JSON.stringify({
  expectedRows: expected,
  renderedRows: rowNames.length,
  childRows: seq.filter(x => x.kind === 'child').length,
  outOfOrderAt,
  firstOutOfOrder: outOfOrderAt >= 0 ? rowNames.slice(outOfOrderAt, outOfOrderAt + 2) : [],
  repeated: repeats(rowNames),
  sitesWithChildrenOutOfOrder: childOutOfOrder,
  childRepeats,
  bands: seq.filter(x => x.kind === 'band').length,
  emptyBands,
  namelessRows: rowNames.filter(nm => !nm).length,
}));
"""


def _render(cluster: int, tab: str) -> dict:
    node = shutil.which("node")
    if not node:  # pragma: no cover - node is present in CI and locally
        raise unittest.SkipTest("node is not available")
    r = subprocess.run(
        [node, "-e", PROGRAM, str(CLOUD_JS), str(cluster), tab],
        capture_output=True, text=True, encoding="utf-8",
        timeout=NODE_TIMEOUT_S,
    )
    if r.returncode != 0:
        raise AssertionError("render failed:\n" + (r.stderr or "")[-3000:])
    return json.loads(r.stdout.strip().splitlines()[-1])


class TheListReadsAsAListTests(unittest.TestCase):
    """98 sites, 18 local folders - the size the complaint was made about."""

    def _check(self, cluster: int, tab: str) -> None:
        got = _render(cluster, tab)

        self.assertEqual(
            got["renderedRows"], got["expectedRows"],
            f"{tab}: {got['expectedRows']} rows of data rendered as "
            f"{got['renderedRows']} rows",
        )

        # "it wasn't in alphabetical order"
        self.assertEqual(
            got["outOfOrderAt"], -1,
            f"{tab}: row {got['outOfOrderAt']} breaks the order: "
            f"{got['firstOutOfOrder']}",
        )

        # "there was repetition"
        self.assertEqual(
            got["repeated"], [],
            f"{tab}: {len(got['repeated'])} name(s) rendered on more than one "
            f"row, first: {got['repeated'][:2]}",
        )

        # The one that was still true. A band the eye has to cross with
        # nothing under it is length rather than information.
        self.assertEqual(
            got["emptyBands"], [],
            f"{tab}: {len(got['emptyBands'])} section band(s) with no rows "
            f"under them: {''.join(got['emptyBands'])}",
        )

        # Every row identifies itself; a blank one is the truncation problem
        # arriving by another door.
        self.assertEqual(got["namelessRows"], 0, f"{tab}: rows with no name")

        # A site's projects are a list too, and get the same two properties.
        self.assertEqual(
            got["sitesWithChildrenOutOfOrder"], 0,
            f"{tab}: {got['sitesWithChildrenOutOfOrder']} site(s) list their "
            f"projects out of order",
        )
        self.assertEqual(
            got["childRepeats"], [],
            f"{tab}: project(s) listed twice under one site: "
            f"{got['childRepeats'][:2]}",
        )

    def test_flat_when_the_codes_spread_across_the_alphabet(self):
        self._check(26, "projects")

    def test_flat_when_the_codes_cluster_on_a_few_letters(self):
        """His real shape: a handful of prefixes over 98 sites."""
        got = _render(3, "projects")
        self.assertEqual(got["emptyBands"], [])
        # And the bands that remain are only the letters he actually has.
        self.assertEqual(got["bands"], 3, "one band per letter in use")
        self._check(3, "projects")

    def test_tree_when_the_codes_spread_across_the_alphabet(self):
        self._check(26, "sites")

    def test_tree_when_the_codes_cluster_on_a_few_letters(self):
        """Tree is the view he works in, so it gets the same standard."""
        self._check(3, "sites")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
