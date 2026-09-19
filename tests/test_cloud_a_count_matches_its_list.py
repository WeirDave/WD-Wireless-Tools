"""A chip's number and the rows it shows have to be answers to one question.

"I got to the unpaired one, it says zero unpaired, and when I click it there's
two unassigned projects on the cloud side."

The code called two unrelated states `orphan`:

* a cloud project with **no matching local .esx**, or a local file with no
  cloud project - our own idea, about pairing two places;
* a cloud project filed under **no site** in Ekahau - Ekahau's idea, and
  Ekahau's own word for it is *assigned*.

The chip counted the first. Its view rendered the second as well. So the number
and the list were answers to different questions, and he got zero and then two
rows - which is the tool telling him something untrue about his own account, in
the one place he looks to decide what to do next.

Both are driven here: `updateDashboard` fills the counts against the real
markup, `renderSitesTree` draws the list for the same data, and the two are
compared. A count that is not the length of its own list fails.
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
CLOUD_HTML = ROOT / "web" / "cloud.html"
NODE_TIMEOUT_S = 120

PROGRAM = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const html = fs.readFileSync(process.argv[2], 'utf8');

function cut(from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return src.slice(a, b);
}

/* Counts are written into the real page, so a chip that is not there cannot
   quietly be counted. */
const ELS = [];
const tagRe = /<(button|span|div|input|details|summary|label)\b([^>]*)>/g;
let m;
while ((m = tagRe.exec(html)) !== null) {
  const attrs = m[2];
  const classes = new Set((((/\bclass="([^"]+)"/.exec(attrs) || [])[1]) || '')
    .split(/\s+/).filter(Boolean));
  const el = { tagName: m[1].toUpperCase(),
    id: (/\bid="([^"]+)"/.exec(attrs) || [])[1] || '',
    dataset: {}, hidden: false, textContent: '-', _at: m.index, _classes: classes,
    style: {},
    classList: { add: c => classes.add(c), remove: c => classes.delete(c),
                 contains: c => classes.has(c),
                 toggle: (c, on) => { if (on === undefined) on = !classes.has(c);
                                      if (on) classes.add(c); else classes.delete(c); } },
    setAttribute: () => {}, getAttribute: () => null,
    querySelector: () => null, querySelectorAll: () => [] };
  const f = (/\bdata-filter="([^"]+)"/.exec(attrs) || [])[1];
  if (f) el.dataset.filter = f;
  ELS.push(el);
}
const byId = new Map(ELS.filter(e => e.id).map(e => [e.id, e]));
function matches(el, sel) {
  if (sel === '[data-filter]') return !!el.dataset.filter;
  const x = /^\[data-filter="([^"]+)"\]$/.exec(sel);
  if (x) return el.dataset.filter === x[1];
  if (sel.startsWith('.')) return sel.slice(1).split(/[.\s]/).filter(Boolean)
      .every(c => el._classes.has(c));
  return false;
}
globalThis.document = {
  getElementById: id => byId.get(id) || null,
  querySelectorAll: sel => ELS.filter(e => matches(e, sel)),
  querySelector: sel => ELS.find(e => matches(e, sel)) || null,
};
globalThis.window = globalThis;

const WD = { esc: s => String(s == null ? '' : s).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])) };
WD.escAttr = WD.esc;
WD.escJsStr = s => String(s == null ? '' : s).replace(/['\\]/g, '\\$&');
function e(s){return WD.esc(s);} function a(s){return WD.escAttr(s);}
function j(s){return WD.escJsStr(s);}
function p(s){return a(String(s==null?'':s).replace(/\\/g,'/'));}
function pj(s){return j(String(s==null?'':s).replace(/\\/g,'/'));}

let currentTab = 'sites';
let activeFilter = 'all';
let dupData = null;
let selected = new Set();
let collapsed = new Set();
let activeLetter = '';
let _searching = false;
let _outputDir = '';
let rowData = {};
const _compareResults = new Map();
function _compareKey(c, l) { return String(c) + '\u0000' + String(l).toLowerCase(); }
function ownerFilter() { return 'all'; }
function renderOwnerFilterNotice() {}
function renderRows() {}
function fmtRelDate(t) { return String(t); }
function charDiff(x, y) { return { a: e(x), b: e(y) }; }
function dupHintFor() { return ''; }
function previewBadge() { return ''; }
function _verifyFailedClass() { return ''; }
function _dupBadge() { return ''; }
function emptyLedgerMessage() { return ''; }
function renderHeldBackSection() { return ''; }
function _collectHeldBack() { return []; }
function _collectAutoAssignable() { return []; }
function _autoAssignDetailsOpen() { return false; }
function toggleFolder() {}
const navigator = { platform: 'Win32' };

const OWNER = 'me@example.com';
function cl(id, name, extra) {
  return Object.assign({ id, name, mtime: 200, owner: OWNER, siteName: '' }, extra || {});
}
function lo(name, extra) {
  return Object.assign({ name, path: 'D:/E/' + name + '.esx', mtime: 100 }, extra || {});
}
function kids() {
  return { matched: [{ cloud: cl('k1', 'Inside'), local: lo('Inside'),
                       matchType: 'id', staleness: null, namesDiffer: false }],
           cloudOnly: [], localOnly: [], heldBack: [] };
}

/* His shape, as he described it: sites that are all paired, and two cloud
   projects Ekahau has filed under no site at all. */
const data = {
  currentUser: OWNER,
  summary: { matched: 2 },
  matched: [
    { cloud: cl('s1', 'Site One', { children: kids() }),
      local: lo('Site One', { isDir: true, children: kids() }),
      matchType: 'exact', namesDiffer: false, staleness: null },
    { cloud: cl('s2', 'Site Two', { children: kids() }),
      local: lo('Site Two', { isDir: true, children: kids() }),
      matchType: 'exact', namesDiffer: false, staleness: null },
  ],
  cloudOnly: [],
  localOnly: [],
  orphans: { cloudOnly: [cl('u1', 'Loose One', { unassigned: true }),
                         cl('u2', 'Loose Two', { unassigned: true })] },
};

/* A site somebody else owns, holding two projects that are his. This is the
   shape behind "3 folders that don't have projects underneath them". */
function theirSite() {
  const kids = { matched: [
      { cloud: cl('m1', 'Mine One'), local: lo('Mine One'),
        matchType: 'id', staleness: null, namesDiffer: false },
      { cloud: cl('m2', 'Mine Two'), local: lo('Mine Two'),
        matchType: 'id', staleness: null, namesDiffer: false }],
    cloudOnly: [], localOnly: [], heldBack: [] };
  return { cloud: cl('t1', 'Their Site', { owner: 'someone.else@example.com',
                                           children: kids }),
           local: lo('Their Site', { isDir: true, children: kids }),
           matchType: 'exact', namesDiffer: false, staleness: null };
}

/* Five slices that do not overlap. `ICONS` and `siteDigest` sit between
   `renderTreeChildren` and `matchBadgeHtml`, so a slice reaching from the
   first to the last pulls them in twice and Node stops at the second
   `const ICONS`. */
eval(cut('function _markActiveFilter(', '\nfunction charDiff(')
   + cut('function buildPassOwner(', '\nfunction _collectAutoAssignable(')
   + cut('function renderSitesTree(', '\nfunction _collectHeldBack(')
   + cut('function _siteMatchesFilterAlone(', '\nconst ICONS = {')
   + cut('const ICONS = {', '\nfunction localByPath('));

function countsFor(filter) {
  activeFilter = filter;
  updateDashboard();
  const out = {};
  byId.forEach((el, id) => { if (/^d[A-Z]/.test(id)) out[id] = String(el.textContent); });
  return out;
}

function rowsFor(filter) {
  activeFilter = filter;
  const hit = () => true;
  const pass = (status) => {
    if (filter === 'all') return true;
    if (filter === 'unassigned') return false;   // site rows, not projects
    return false;
  };
  const html = renderSitesTree(hit, pass, buildPassOwner('all', OWNER), false);
  // Every cloud project drawn under the "no site" heading.
  const i = html.indexOf('tree-orphan-head');
  if (i < 0) return { unassignedRows: 0 };
  return { unassignedRows: (html.slice(i).match(/class="lr-cell cloud/g) || []).length };
}

const out = {};
out.counts = countsFor('all');
out.underAll = rowsFor('all');
out.underUnassigned = rowsFor('unassigned');
// External, on a site owned by somebody else whose contents are his.
data.matched = [theirSite()];
activeFilter = 'external';
updateDashboard();
{
  const hit = () => true;
  const pass = (st, row) => _siteMatchesFilterAlone({ cloud: row && row.cloud,
                                                      local: row && row.local,
                                                      status: st })
                            || _isExternal(row && row.cloud, row && row.local);
  const html = renderSitesTree(hit, pass, buildPassOwner('all', OWNER), false);
  out.external = {
    siteRows: (html.match(/ledger-row tree-parent/g) || []).length,
    childRows: (html.match(/ledger-row tree-child/g) || []).length,
  };
}

/* "cloud only says zero and shows me two unassigned projects ... which is
   correct, which means the number should actually be 2, not 0" */
data.matched = [
  { cloud: cl('s1', 'Site One', { children: kids() }),
    local: lo('Site One', { isDir: true, children: kids() }),
    matchType: 'exact', namesDiffer: false, staleness: null }];
out.cloudOnlyCount = countsFor('orphans-cloud').dCloudOnly;
{
  activeFilter = 'orphans-cloud';
  const html = renderSitesTree(() => true, (st, row) => st === 'orphan'
      && row && row.cloud && !row.local, buildPassOwner('all', OWNER), false);
  const i = html.indexOf('tree-orphan-head');
  out.cloudOnlyRows = i < 0 ? 0
    : (html.slice(i).match(/class="lr-cell cloud/g) || []).length;
}

/* "not shared says 97 and it's showing site names with no projects ... you
   don't actually share sites on Ekahau" - so it counts projects. One site,
   one project inside it, nobody else given access. */
data.matched = [
  { cloud: cl('s9', 'Lonely Site', { sharedWith: [], children: {
      matched: [{ cloud: cl('p9', 'Lonely Project', { sharedWith: [] }),
                  local: lo('Lonely Project'), matchType: 'id',
                  staleness: null, namesDiffer: false }],
      cloudOnly: [], localOnly: [], heldBack: [] } }),
    local: lo('Lonely Site', { isDir: true }),
    matchType: 'exact', namesDiffer: false, staleness: null }];
data.orphans = { cloudOnly: [] };
out.unsharedCount = countsFor('unshared').dUnshared;

/* "sites should not be counted in those - we should only have a button for
   unmatched sites." Two sites, one of them with no local folder; inside the
   matched one, a project whose names differ and a project with no local copy. */
data.matched = [
  { cloud: cl('s1', 'Site One', { children: {
      matched: [{ cloud: cl('a1', 'A One'), local: lo('A One v2'),
                  matchType: 'exact', staleness: null, namesDiffer: true }],
      cloudOnly: [cl('a2', 'A Two')], localOnly: [], heldBack: [] } }),
    local: lo('Site One', { isDir: true }),
    matchType: 'exact', namesDiffer: true, staleness: null }];
data.cloudOnly = [cl('s2', 'Site Two', { children: {
    matched: [], cloudOnly: [], localOnly: [], heldBack: [] } })];
data.localOnly = [lo('Folder Three', { isDir: true, children: {
    matched: [], cloudOnly: [], localOnly: [], heldBack: [] } })];
data.orphans = { cloudOnly: [] };
out.siteTab = countsFor('all');

out.filtersOffered = ELS.filter(x => x.dataset.filter && !x.hidden)
                        .map(x => x.dataset.filter);
console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ACountIsTheLengthOfItsOwnList(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", PROGRAM, str(CLOUD_JS), str(CLOUD_HTML)],
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        cls.out = json.loads(r.stdout.strip().splitlines()[-1])

    def test_not_assigned_counts_the_rows_it_shows(self):
        """The reported case. Two cloud projects under no site, and the chip
        that selects them says two."""
        self.assertEqual("2", self.out["counts"]["dUnassigned"])
        self.assertEqual(2, self.out["underUnassigned"]["unassignedRows"])

    def test_they_are_still_visible_under_all(self):
        """Filing nothing away: All means all."""
        self.assertEqual(2, self.out["underAll"]["unassignedRows"])

    # `test_a_site_that_matched_on_its_own_keeps_its_contents` was here, and
    # it asserted the behaviour that "site names should not be external" has
    # since replaced: a site owned by somebody else satisfied `external` by
    # itself, the same test was applied to each project inside it - all of
    # which are his - and the folder survived while its contents did not.
    # Showing the contents fixed the symptom and kept the category error.
    #
    # It is not rewritten in place because this probe hands `renderSitesTree`
    # a predicate it writes itself, so it cannot exercise the real rule - the
    # weakness that let the owner-filter defect through here too.
    # `test_cloud_a_chip_agrees_with_its_list_for_every_owner.py` drives the
    # real `renderLedger` and holds the new rule.

    def test_cloud_only_counts_the_site_less_projects_it_shows(self):
        """"it says zero cloud only and it shows me two unassigned projects on
        the cloud side that are not on the local side, which is correct, which
        means the number should actually be 2, not 0."

        They are two things at once - filed under no site, and in the cloud
        with nothing matching on disk. The list had always drawn them here;
        the count was the only thing that never looked.
        """
        self.assertEqual("2", self.out["cloudOnlyCount"])
        self.assertEqual(2, self.out["cloudOnlyRows"])

    def test_not_shared_counts_projects_because_sharing_is_a_project(self):
        """"it says there's 97 not shared and it's showing site names with no
        projects, which means it's counting the site names as not shared - and
        you don't actually share sites on Ekahau."

        One site holding one unshared project is one answer, not two.
        """
        self.assertEqual("1", self.out["unsharedCount"])

    def test_name_mismatches_counts_projects_not_sites(self):
        """"sites should not be counted in those."

        One site whose name differs from its folder, holding one project whose
        name differs from its file. The answer is one - the project - and the
        site is not part of it.
        """
        self.assertEqual("1", self.out["siteTab"]["dMismatches"])

    def test_cloud_only_counts_projects_not_sites(self):
        """One cloud-only project inside a matched site, and one cloud-only
        *site*. The site is not the answer here."""
        self.assertEqual("1", self.out["siteTab"]["dCloudOnly"])
        self.assertEqual("0", self.out["siteTab"]["dLocalOnly"])

    def test_unmatched_sites_is_the_one_chip_that_counts_sites(self):
        """"we should only have a button for unmatched sites that would show
        sites on cloud that don't have a folder equivalent or vice versa."

        Both directions, one number: a cloud site with no folder, and a folder
        with no cloud site.
        """
        self.assertEqual("2", self.out["siteTab"]["dUnmatchedSites"])

    def test_not_assigned_is_offered_on_the_sites_tab(self):
        """It was Projects-only, while these rows render on Sites - so on the
        tab where he could see them, nothing selected them."""
        self.assertIn("unassigned", self.out["filtersOffered"])


class OneWordForOneThing(unittest.TestCase):
    """"every time we make up more terms that mean the same it gets confusing,
    we need to use the terminology that Ekahau is already using."

    Two states were both called `orphan` in the code and the UI inherited the
    ambiguity as "unpaired": no counterpart on the other side, and no site in
    Ekahau. They are different questions with different answers.
    """

    HTML = CLOUD_HTML.read_text(encoding="utf-8")

    def labels(self):
        return re.findall(r'<span class="sum-l">([^<]+)</span>', self.HTML)

    def test_there_is_no_umbrella_over_cloud_only_and_local_only(self):
        """"unpaired" was a third word for the axis those two already cover,
        and it was the one whose count did not match its list."""
        self.assertNotIn("unpaired", self.labels())
        self.assertIn("cloud only", self.labels())
        self.assertIn("local only", self.labels())

    def test_the_site_filter_uses_ekahau_s_word(self):
        """Ekahau assigns a project to a site. The row menu already offers
        Assign and the row tag already reads "Not assigned"; the filter said
        "no site", which was a fourth way of saying it."""
        self.assertIn("not assigned", self.labels())
        self.assertNotIn("no site", self.labels())

    def test_its_tooltip_says_whose_word_it_is(self):
        chip = re.search(r'<button class="sum-count" data-filter="unassigned".*?</button>',
                         self.HTML, re.S).group(0)
        self.assertIn("assigned to a site in Ekahau", chip)

    def test_no_chip_label_repeats_another(self):
        """Two chips meaning the same thing is the complaint itself."""
        labels = self.labels()
        self.assertEqual(len(labels), len(set(labels)), labels)


if __name__ == "__main__":
    unittest.main()
