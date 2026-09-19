"""Auto-assign assigns the projects it listed, and nothing else.

The banner offers a count and, behind a chevron, the projects and their
destinations one per line. It is built from the rows that survived the filter,
the search and the A-Z letter - what is on screen.

`autoAssignAllMatched` did not use that list. It called
`_visibleSiteRowsForBatch()`, which rebuilt every row from `data` with no
filter, no search and no letter applied - "visible" in name only. So typing in
the search box narrowed the banner to one project and left the button
assigning every unassigned project in the account.

That writes to Ekahau. The projects it filed away were never named on screen,
and the ops deck showed more operations than the button had offered.

The band above it already had the answer: `uncomparedBandHtml` stores the set
it drew in `_uncomparedNow` at render time, "because that is when the filter
predicates exist and it is exactly the set he can see", and `checkAllUncompared`
runs that stored set. Auto-assign does the same now.

The whole of `cloud.js` is evaluated against the real page, so the banner is
rendered by the real renderer and the handler is the real handler.

Every project, site and address here is invented.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
CLOUD_HTML = ROOT / "web" / "cloud.html"
NODE_TIMEOUT_S = 120

NODE_SCRIPT = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const html = fs.readFileSync(process.argv[2], 'utf8');

function mkEl(tag, attrs) {
  attrs = attrs || {};
  const classes = new Set((attrs.class || '').split(/\s+/).filter(Boolean));
  const el = {
    tagName: (tag || 'div').toUpperCase(), id: attrs.id || '',
    dataset: {}, hidden: false, textContent: '', innerHTML: '', value: '',
    disabled: false, checked: false, style: {}, children: [], _classes: classes,
    _attrs: attrs,
    classList: { add: c => classes.add(c), remove: c => classes.delete(c),
      contains: c => classes.has(c),
      toggle: (c, on) => { if (on === undefined) on = !classes.has(c);
        if (on) classes.add(c); else classes.delete(c); } },
    setAttribute: (k, v) => { el._attrs[k] = v; },
    getAttribute: k => (k in el._attrs ? el._attrs[k] : null),
    removeAttribute: k => { delete el._attrs[k]; },
    addEventListener: () => {}, removeEventListener: () => {},
    appendChild: c => { el.children.push(c); return c; },
    removeChild: () => {}, remove: () => {}, focus: () => {}, blur: () => {},
    click: () => {}, closest: () => null, contains: () => false,
    scrollIntoView: () => {},
    getBoundingClientRect: () => ({top:0,left:0,width:0,height:0,bottom:0,right:0}),
    querySelector: () => null, querySelectorAll: () => [],
    insertAdjacentHTML: () => {},
  };
  for (const [k, v] of Object.entries(attrs)) {
    if (k.startsWith('data-')) el.dataset[k.slice(5)] = v;
  }
  return el;
}

const ELS = [];
const tagRe = /<(button|span|div|input|details|summary|label|select|option|textarea|section|p|a|h1|h2|h3|ul|li|nav|header|footer)\b([^>]*)>/g;
let m;
while ((m = tagRe.exec(html)) !== null) {
  const attrs = {};
  let am; const aRe = /([A-Za-z_:][-A-Za-z0-9_:.]*)(?:="([^"]*)")?/g;
  while ((am = aRe.exec(m[2])) !== null) attrs[am[1]] = am[2] === undefined ? '' : am[2];
  ELS.push(mkEl(m[1], attrs));
}
const byId = new Map(ELS.filter(e => e.id).map(e => [e.id, e]));
function matches(el, sel) {
  sel = sel.trim();
  if (!sel) return false;
  const x = /^\[data-filter="([^"]+)"\]$/.exec(sel);
  if (x) return el.dataset.filter === x[1];
  if (sel === '[data-filter]') return !!el.dataset.filter;
  if (sel.startsWith('#')) return el.id === sel.slice(1);
  if (sel.startsWith('.')) {
    return sel.slice(1).split(/[.\s]/).filter(Boolean).every(c => el._classes.has(c));
  }
  return el.tagName === sel.toUpperCase();
}
globalThis.document = {
  getElementById: id => byId.get(id) || null,
  querySelectorAll: sel => ELS.filter(e => sel.split(',').some(s => matches(e, s))),
  querySelector: sel => ELS.find(e => sel.split(',').some(s => matches(e, s))) || null,
  createElement: t => mkEl(t),
  addEventListener: () => {}, removeEventListener: () => {},
  body: mkEl('body'), documentElement: mkEl('html'),
  scrollingElement: Object.assign(mkEl('html'), { scrollTop: 0 }),
};
const store = {};
globalThis.localStorage = {
  getItem: k => (k in store ? store[k] : null),
  setItem: (k, v) => { store[k] = String(v); },
  removeItem: k => { delete store[k]; },
};
globalThis.navigator = { platform: 'Win32' };
globalThis.location = { href: 'http://localhost/cloud.html', search: '' };
globalThis.fetch = async () => ({ ok: true, json: async () => ({}) });
globalThis.requestAnimationFrame = fn => setTimeout(fn, 0);
globalThis.matchMedia = () => ({ matches: false, addEventListener() {}, addListener() {} });
const BS = String.fromCharCode(92);
const WD = {
  esc: s => String(s == null ? '' : s).replace(/[&<>"]/g,
    c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])),
  toast: () => {}, api: async () => ({}), toggleMenu: () => {},
};
WD.escAttr = WD.esc;
WD.escJsStr = s => String(s == null ? '' : s)
  .split(BS).join(BS + BS).split("'").join(BS + "'");
globalThis.WD = WD;
globalThis.toast = () => {};
globalThis.showModal = () => {};
globalThis.hideModal = () => {};
globalThis.window = globalThis;

const tail = `
;globalThis.__set = (k, v) => {
  switch (k) {
    case 'data': data = v; break;
    case 'currentTab': currentTab = v; break;
    case 'activeFilter': activeFilter = v; break;
    case 'activeLetter': activeLetter = v; break;
    case '_searching': _searching = v; break;
    default: throw new Error('no setter for ' + k);
  }
};
`;
(0, eval)(src + tail);

// Every assignment that actually reaches the server is recorded here.
const assigned = [];
globalThis.pyApi = async (method, ...args) => {
  if (method === 'assign_to_site') assigned.push({ siteId: args[0], projectId: args[1] });
  return { ok: true };
};
// Run each queued operation immediately, so the deck is not the thing on test.
globalThis.opEnqueue = (spec) => {
  const p = Promise.resolve().then(() => spec.run('op'));
  return { id: 'op', promise: p };
};

const ME = 'me@example.invalid';
const proj = (id, name) => ({ id, name, mtime: 200, owner: ME, siteName: '',
                              unassigned: true, hasSite: false });
const lo = (name, extra) => Object.assign(
  { name, path: 'D:/Ekahau Projects/' + name + '.esx', mtime: 200, isDir: false }, extra || {});

function site(name, kidNames) {
  const children = {
    matched: kidNames.map((k, i) => ({
      cloud: proj('u-' + name + '-' + i, k), local: lo(k),
      matchType: 'id', namesDiffer: false, staleness: null, status: 'synced' })),
    cloudOnly: [], localOnly: [], heldBack: [],
  };
  return {
    cloud: { id: 's-' + name, name, mtime: 200, owner: ME, siteName: '',
             hasSite: true, children },
    local: lo(name, { isDir: true, children }),
    matchType: 'exact', namesDiffer: false, staleness: null, status: 'synced',
  };
}

__set('data', { currentUser: ME, summary: { matched: 2 },
  matched: [site('Alpha Depot', ['Alpha Baseline']),
            site('Bravo Works', ['Bravo Baseline', 'Bravo Phase 2'])],
  cloudOnly: [], localOnly: [], orphans: { cloudOnly: [] } });
__set('currentTab', 'sites');
__set('activeFilter', 'all');
__set('activeLetter', '');

const out = {};

async function run(searchTerm) {
  // Render exactly as `renderRows` does, with the search box filled in.
  const box = byId.get('searchBox');
  if (box) box.value = searchTerm || '';
  __set('_searching', !!searchTerm);
  const markup = renderLedger(n => !searchTerm ||
    String(n || '').toLowerCase().includes(searchTerm.toLowerCase()));
  const offered = (markup.match(/aab-detail-row/g) || []).length;
  const label = (/Auto-assign (\d+)/.exec(markup) || [])[1];
  assigned.length = 0;
  await autoAssignAllMatched();
  await new Promise(r => setTimeout(r, 0));
  return { offered, label: label ? Number(label) : null,
           assigned: assigned.map(a => a.projectId).sort() };
}

// ---- A chip that has something to show has to be reachable ----------------
// A project inside a site, owned by somebody else. On the Sites tab the count
// is taken from the projects (`kidExternal`) and the visibility was taken from
// a different variable that is always zero on that tab.
const OTHER = 'colleague@example.invalid';
function siteHoldingTheirProject() {
  const kid = {
    cloud: { id: 'x-1', name: 'Their Survey', mtime: 200, owner: OTHER,
             siteName: '', hasSite: true },
    local: lo('Their Survey'),
    matchType: 'id', namesDiffer: false, staleness: null, status: 'synced' };
  const children = { matched: [kid], cloudOnly: [], localOnly: [], heldBack: [] };
  return { cloud: { id: 's-x', name: 'Shared Depot', mtime: 200, owner: ME,
                    siteName: '', hasSite: true, children },
           local: lo('Shared Depot', { isDir: true, children }),
           matchType: 'exact', namesDiffer: false, staleness: null,
           status: 'synced' };
}

function externalChip(tab, rows) {
  __set('data', { currentUser: ME, summary: { matched: rows.length },
    matched: rows, cloudOnly: [], localOnly: [], orphans: { cloudOnly: [] } });
  __set('currentTab', tab);
  __set('activeFilter', 'all');
  setOwnerFilter('all');
  updateDashboard();
  const chip = document.querySelector('[data-filter="external"]');
  return { count: byId.get('dExternal').textContent,
           hidden: chip ? !!chip.hidden : null };
}

(async () => {
  out.everything = await run('');
  out.searched = await run('alpha');

  // ---- the search has to reach inside a site -----------------------------
  function searchTree(term) {
    __set('data', { currentUser: ME, summary: { matched: 2 },
      matched: [site('Alpha Depot', ['Alpha Baseline']),
                site('Bravo Works', ['Bravo Baseline', 'Bravo Phase 2'])],
      cloudOnly: [], localOnly: [], orphans: { cloudOnly: [] } });
    __set('currentTab', 'sites');
    __set('activeFilter', 'all');
    setOwnerFilter('all');
    const box = byId.get('searchBox');
    if (box) box.value = term;
    __set('_searching', !!term);
    const markup = renderLedger(n =>
      String(n || '').toLowerCase().includes(term.toLowerCase()));
    return {
      sites: (markup.match(/ledger-row tree-parent/g) || []).length,
      children: (markup.match(/ledger-row tree-child /g) || []).length,
      names: [...markup.matchAll(/class="lr-name"[^>]*>([^<]*)</g)].map(x => x[1]),
    };
  }
  out.searchOneProject = searchTree('bravo phase 2');
  out.searchSiteName = searchTree('bravo works');

  out.externalSites = externalChip('sites', [siteHoldingTheirProject()]);
  const theirProject = siteHoldingTheirProject().cloud.children.matched[0];
  out.externalProjects = externalChip('projects', [theirProject]);
  out.externalNoneSites = externalChip('sites', [site('Alpha Depot', ['Alpha Baseline'])]);

  process.stdout.write(JSON.stringify(out));
  process.exit(0);
})().catch(err => { process.stderr.write(String(err && err.stack || err)); process.exit(1); });
"""

_PROBE = {}


def probe():
    if not _PROBE:
        proc = subprocess.run(
            ["node", "-e", NODE_SCRIPT, str(CLOUD_JS), str(CLOUD_HTML)],
            capture_output=True, text=True, encoding="utf-8",
            timeout=NODE_TIMEOUT_S)
        if proc.returncode != 0:
            raise AssertionError("node failed:\n" + proc.stderr)
        _PROBE.update(json.loads(proc.stdout))
    return _PROBE


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class AutoAssignActsOnWhatItOffered(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = probe()

    def test_with_no_search_it_offers_and_assigns_all_three(self):
        """Refusing is only correct if it refuses the right thing."""
        self.assertEqual(3, self.out["everything"]["label"])
        self.assertEqual(3, self.out["everything"]["offered"])
        self.assertEqual(3, len(self.out["everything"]["assigned"]))

    def test_a_search_narrows_the_button_as_well_as_the_banner(self):
        """The banner said one and the button filed three - two of them in a
        site that was not on screen, named nowhere, straight to Ekahau."""
        self.assertEqual(1, self.out["searched"]["label"],
                         "the fixture did not actually narrow the banner")
        self.assertEqual(
            1, len(self.out["searched"]["assigned"]),
            "the button assigned projects the banner never offered: "
            + repr(self.out["searched"]["assigned"]))

    def test_the_project_assigned_is_the_one_that_was_listed(self):
        self.assertEqual(["u-Alpha Depot-0"], self.out["searched"]["assigned"])


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class TheSearchReachesInsideASite(unittest.TestCase):
    """Searching for one project shows one project.

    `renderTreeChildren` takes `hit` as its second parameter and never
    referenced it. A site survived the search through `childHit`, `_searching`
    forced it open, and then every project inside it was drawn - so searching
    for one survey in a site of a dozen returned all twelve.

    The rule already exists one level up, for the chip filter: matched by
    itself, show everything in it; matched through a child, show the children
    that matched. The search follows the same rule now.
    """

    @classmethod
    def setUpClass(cls):
        cls.out = probe()

    def test_searching_a_project_name_shows_that_project_alone(self):
        got = self.out["searchOneProject"]
        self.assertEqual(1, got["sites"], got)
        self.assertEqual(1, got["children"],
                         "the whole site was drawn for a one-project search: "
                         + repr(got))

    def test_searching_a_site_name_still_shows_everything_in_it(self):
        """The site itself matched, so its contents are what he asked for."""
        got = self.out["searchSiteName"]
        self.assertEqual(1, got["sites"], got)
        self.assertEqual(2, got["children"], got)


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class AChipWithSomethingToShowIsReachable(unittest.TestCase):
    """A count written next to a chip nobody can click is not a count.

    On the Sites tab every chip counts the projects inside the sites, and the
    External count is taken from `kidExternal`. Its *visibility* was taken
    from `externalCount`, which is only ever incremented through a helper that
    begins `!isSitesTab` - so on the Sites tab it is always zero and the chip
    was hidden however many external projects were there.

    The Sites tab is the default view, and the chip's own tooltip in
    `cloud.html` describes Sites-tab behaviour: "On the Sites tab a site is
    listed when a project inside it is one of these."
    """

    @classmethod
    def setUpClass(cls):
        cls.out = probe()

    def test_the_sites_tab_offers_the_chip_it_has_counted(self):
        got = self.out["externalSites"]
        self.assertEqual("1", str(got["count"]), got)
        self.assertFalse(got["hidden"],
                         "the chip counted 1 and was hidden: " + repr(got))

    def test_the_projects_tab_is_unaffected(self):
        got = self.out["externalProjects"]
        self.assertEqual("1", str(got["count"]), got)
        self.assertFalse(got["hidden"], got)

    def test_a_chip_with_nothing_to_show_stays_hidden(self):
        """Showing it always would just be the opposite mistake."""
        got = self.out["externalNoneSites"]
        self.assertEqual("0", str(got["count"]), got)
        self.assertTrue(got["hidden"], got)


if __name__ == "__main__":
    unittest.main()
