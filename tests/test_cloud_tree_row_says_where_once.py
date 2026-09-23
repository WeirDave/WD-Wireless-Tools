"""On the Tree, a row does not repeat - or contradict - the row above it.

Two things reported off one screen, and they turned out to be one defect:

* "a couple of the [projects] in the same parent folder showed **no site**,
  meaning they weren't assigned to a site on the cloud, and yet they're listed
  underneath the site on the cloud side." A row saying it has no site, drawn
  inside the site it is filed in, is the tool contradicting itself in the space
  of one line.
* "on the right hand side ... we have the ESX files and now for whatever reason
  we're showing the folder. But that's dumb, because the folder equates to the
  site on the cloud side." The site and the folder are already paired on the
  parent row; naming the folder again on every child is the same word a second
  time in a smaller font.

The cause of both was `locationDiffers`, which is a **Flat** idea: Flat pairs a
cloud project with a local .esx wherever either happens to be, so where each one
sits is the question. It guarded itself with `r.kind`, and `renderTreeChildren`
sets `kind: 'projects'` on every child so the row menu offers project actions -
so the guard was satisfied on the Tree too. There it had nothing true to say:
`build_sites_data` gives a tree child a `folder` and no `siteName`, so every
single child compared '' against its folder name, found a disagreement, and drew
both halves of it. Not only the unassigned ones - *every* row.

Driven through the real renderers. `renderSitesTree` draws the tree and the
cells are pulled back out of the HTML it returns; `cloudCell`/`localCell` draw
the Flat row. Deleting the guard, or putting `r.kind` back, fails this.
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
CLOUD_PY = ROOT / "tools" / "cloud_manager.py"
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

/* Enough of the page for the dashboard helpers the renderer touches. */
const ELS = [];
const tagRe = /<(button|span|div|input|details|summary|label)\b([^>]*)>/g;
let m;
while ((m = tagRe.exec(html)) !== null) {
  const attrs = m[2];
  const classes = new Set((((/\bclass="([^"]+)"/.exec(attrs) || [])[1]) || '')
    .split(/\s+/).filter(Boolean));
  const el = { tagName: m[1].toUpperCase(),
    id: (/\bid="([^"]+)"/.exec(attrs) || [])[1] || '',
    dataset: {}, hidden: false, textContent: '-', _classes: classes, style: {},
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
const byId = new Map(ELS.filter(x => x.id).map(x => [x.id, x]));
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
  querySelectorAll: sel => ELS.filter(x => matches(x, sel)),
  querySelector: sel => ELS.find(x => matches(x, sel)) || null,
};
globalThis.window = globalThis;

const WD = { esc: s => String(s == null ? '' : s).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])) };
WD.escAttr = WD.esc;
WD.escJsStr = s => String(s == null ? '' : s).replace(/['\\]/g, '\\$&');
function e(s){return WD.esc(s);} function a(s){return WD.escAttr(s);}
function j(s){return WD.escJsStr(s);}
function p(s){return a(String(s==null?'':s).replace(/\\/g,'/'));}
function np(s){return String(s==null?'':s).replace(/\\/g,'/');}

let currentTab = 'sites';
let activeFilter = 'all';
let dupData = null;
let selected = new Set();
let collapsed = new Set();
let activeLetter = '';
let _searching = false;
let _outputDir = 'D:/Ekahau';
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
function toggleFolder() {}
globalThis._collectHeldBack = () => [];
globalThis._autoAssignDetailsOpen = () => false;
const navigator = { platform: 'Win32' };

eval(cut('function _markActiveFilter(', '\nfunction charDiff(')
   + cut('function renderSitesTree(', '\nfunction _collectHeldBack(')
   + cut('function buildPassOwner(', '\nconst ICONS = {')
   + cut('const ICONS = {', '\nfunction localByPath('));

const OWNER = 'me@example.com';
const SITE = 'Hollow Pines';

/* The shape `build_sites_data` actually produces: a tree child's cloud side
   carries no `siteName` (the site is the row above), and its local side
   carries the `folder` it was indexed under. */
function cloudChild(id, name, extra) {
  return Object.assign({ id, name, code: null, mtime: 200, owner: OWNER,
                         meta: '12 MB' }, extra || {});
}
function localChild(name, extra) {
  return Object.assign({ name, path: 'D:/Ekahau/' + SITE + '/' + name + '.esx',
                         mtime: 100, folder: SITE, meta: '12 MB' }, extra || {});
}
function pair(id, name, cx) {
  return { cloud: cloudChild(id, name, cx), local: localChild(name),
           matchType: 'id', staleness: null, namesDiffer: false };
}

/* One site, two projects inside it. One is assigned to the site in Ekahau; the
   other is not, and the backend moved it in here because its .esx lives in this
   site's folder. Both were drawing "no site" and the folder name. */
function kids() {
  return { matched: [pair('p1', 'Hollow Pines AP Survey'),
                     pair('p2', 'Hollow Pines Validation', { unassigned: true })],
           cloudOnly: [], localOnly: [], heldBack: [] };
}
const site = () => ({
  cloud: Object.assign(cloudChild('s1', SITE), { children: kids() }),
  local: Object.assign(localChild(SITE), { isDir: true, folder: '',
                                           path: 'D:/Ekahau/' + SITE,
                                           children: kids() }),
  matchType: 'exact', namesDiffer: false, staleness: null,
});

globalThis.data = { currentUser: OWNER, summary: { matched: 1 },
                    matched: [site()], cloudOnly: [], localOnly: [],
                    orphans: { cloudOnly: [] } };

const out = {};

/* --- The Tree, drawn by the real renderer. ------------------------------- */
const tree = renderSitesTree(() => true, () => true,
                             buildPassOwner('all', OWNER), false);

/* Every child row, split into its cloud half and its local half, pulled back
   out of the HTML rather than assumed. */
function childRows(markup) {
  const rows = [];
  const re = /<div class="ledger-row tree-child [^"]*">([\s\S]*?)(?=<div class="ledger-row|<div class="ledger-group-head|$)/g;
  let r;
  while ((r = re.exec(markup)) !== null) {
    const body = r[1];
    const c = body.indexOf('<div class="lr-cell cloud');
    const g = body.indexOf('<div class="lr-gut');
    const l = body.indexOf('<div class="lr-cell local');
    rows.push({ cloud: body.slice(c, g > c ? g : undefined),
                local: body.slice(l) });
  }
  return rows;
}
const rows = childRows(tree);
out.treeChildCount = rows.length;
out.treeCloudSaysNoSite = rows.filter(r => /class="cell-where/.test(r.cloud)).length;
out.treeLocalNamesFolder = rows.filter(r => /class="cell-where/.test(r.local)).length;

/* What a reader can see on the row, as opposed to what is in the markup: tags
   and their attributes dropped, so the paths inside the menu's own onclick
   handlers - which necessarily contain the folder - are not mistaken for the
   folder being *printed* on the row. */
function visibleText(markup) {
  return markup.replace(/<[^>]*>/g, ' ').replace(/\s+/g, ' ').trim();
}
out.treeLocalRepeatsSiteName = rows.filter(r => {
  const withoutName = r.local.replace(/<span class="cell-name">[\s\S]*?<\/span>/, '');
  return visibleText(withoutName).indexOf(SITE) >= 0;
}).length;
out.sampleLocalText = rows.length ? visibleText(rows[0].local) : '';

/* The assignment story is untouched: the project genuinely filed under no site
   still says so, on its name and in its menu, where it can be acted on. */
out.notAssignedTags = (tree.match(/pt-unassigned/g) || []).length;
out.assignMenuItems = (tree.match(/data-fn="assignOrphanToSite"/g) || []).length;

/* --- Flat, where the location tag is the point of the view. -------------- */
currentTab = 'projects';
function flat(siteName, folder) {
  const r = { status: 'synced', kind: 'projects', key: 'p:x',
              cloud: cloudChild('f1', 'Hollow Pines AP Survey', { siteName }),
              local: localChild('Hollow Pines AP Survey', { folder }) };
  return { cloud: cloudCell(r, new Set()), local: localCell(r, new Set()) };
}
const agree = flat(SITE, SITE);
const differ = flat(SITE, 'Loose Files');
out.flatAgreeTags = (agree.cloud + agree.local).match(/class="cell-where/g);
out.flatDifferTags = (differ.cloud + differ.local).match(/class="cell-where/g);
out.flatAgreeTags = (out.flatAgreeTags || []).length;
out.flatDifferTags = (out.flatDifferTags || []).length;

console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheTreeSaysWhereOnce(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", PROGRAM, str(CLOUD_JS), str(CLOUD_HTML)],
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        cls.out = json.loads(r.stdout.strip().splitlines()[-1])

    def test_the_fixture_actually_drew_the_rows(self):
        """A count of zero would pass everything below it for the wrong
        reason."""
        self.assertEqual(2, self.out["treeChildCount"])

    def test_no_row_inside_a_site_claims_to_have_no_site(self):
        """The reported contradiction: "no site", underneath the site."""
        self.assertEqual(0, self.out["treeCloudSaysNoSite"])

    def test_the_local_side_does_not_name_the_folder_again(self):
        """"the folder equates to the site on the cloud side" - it is the row
        above, and the .esx row is the file."""
        self.assertEqual(0, self.out["treeLocalNamesFolder"])
        self.assertEqual(0, self.out["treeLocalRepeatsSiteName"])

    def test_a_project_with_no_site_still_says_so_where_it_can_be_fixed(self):
        """Removing the location tag must not take the assignment story with
        it. One of the two is genuinely unassigned: it keeps its tag, and its
        menu still offers to file it under the site it is sitting in."""
        self.assertEqual(1, self.out["notAssignedTags"])
        self.assertEqual(1, self.out["assignMenuItems"])

    def test_flat_still_says_where_when_the_two_sides_disagree(self):
        """That is what the tag is for, and the Flat tab is where it belongs:
        a .esx in the wrong folder is worth the row. When they agree, it is the
        same word twice and is not drawn."""
        self.assertEqual(0, self.out["flatAgreeTags"])
        self.assertEqual(2, self.out["flatDifferTags"])


class TheTreeChildHasNothingToCompare(unittest.TestCase):
    """Why the tag could never be right on the Tree - established by running
    the builder, not by reading it.

    `build_sites_data` is what fills the Tree. It is run here against a stubbed
    Ekahau and a stubbed disk, and the child rows it produces are inspected: the
    cloud half carries no `siteName`, the local half carries the site's own
    `folder`. So the comparison the location tag makes is '' against the folder
    name, for every row, always - which is why it fired on rows that were
    perfectly well assigned.

    If a later change starts putting a `siteName` on tree children, this fails,
    and the guard in `locationDiffers` wants revisiting rather than quietly
    rotting into a rule nobody remembers the reason for.
    """

    SITE = "Hollow Pines"

    def _build(self):
        import tools.cloud_manager as cm

        class FakeApi:
            def get_sites(self):
                return [{"id": "s1", "name": TheTreeChildHasNothingToCompare.SITE}]

            def get_dataset_listing(self):
                return [{"id": "d1", "siteId": "s1",
                         "siteName": TheTreeChildHasNothingToCompare.SITE,
                         "type": "SURVEY", "datasetUsers": [
                             {"username": "me@example.com", "role": "OWNER"}]}]

            def get_projects(self):
                return [{"id": "d1", "name": "Hollow Pines AP Survey",
                         "statistics": {"size": 1234},
                         "history": {"createdBy": "me@example.com"}}]

        site = self.SITE
        patches = {
            "get_local_folders": lambda _d: [
                {"path": "D:/Ekahau/" + site, "name": site, "code": None,
                 "esxCount": 1, "totalSize": 1234}],
            "get_local_esx_files": lambda _d: [
                {"path": "D:/Ekahau/" + site + "/Hollow Pines AP Survey.esx",
                 "name": "Hollow Pines AP Survey", "folder": site,
                 "size": 1234, "mtime": 100, "owner": "", "projectId": "d1",
                 "projectType": None}],
            "folder_inventory": lambda _p: {"srcCount": 0, "total": 1,
                                            "esx": 1, "plans": 0, "images": 0,
                                            "other": 0, "files": []},
            "not_matches_set": lambda: set(),
            "manual_matches_map": lambda: ({}, {}),
        }
        saved = {k: getattr(cm, k) for k in patches}
        for k, v in patches.items():
            setattr(cm, k, v)
        try:
            return cm.build_sites_data(FakeApi(), "D:/Ekahau")
        finally:
            for k, v in saved.items():
                setattr(cm, k, v)

    def test_a_tree_child_is_not_given_a_site_name(self):
        result = self._build()
        pairs = result["matched"]
        self.assertEqual(1, len(pairs), "the fixture did not pair the site")
        kids = pairs[0]["cloud"]["children"]["matched"]
        self.assertEqual(1, len(kids), "the fixture did not pair the project")
        child = kids[0]
        self.assertNotIn("siteName", child["cloud"],
                         "build_sites_data now supplies siteName on tree "
                         "children - locationDiffers' Tree guard needs "
                         "revisiting, not deleting.")
        self.assertEqual(self.SITE, child["local"]["folder"],
                         "the local half no longer names its folder, so the "
                         "comparison this test explains has changed shape.")
