"""An action is drawn under the side it writes to, and the chip counts its list.

Two things reported off one screen, plus the thing that made them confusing.

**The side.** "the blue buttons are all on the left hand side." One of them was
`Set the name inside the file to match`, which takes the cloud project's name
and writes it into the **local** .esx - nothing reaches Ekahau at all. Drawn
under the Cloud column it read as a cloud action, so when it then failed on a
local file the error made no sense against the place the button was sitting:
"I think that's exactly backwards."

It was never a cloud lane. The band was one flex row spanning the whole width,
so every button piled up at the left margin and the right half was empty - which
is worse than a wrong label, because it looks like a column and is not one.

Three lanes now, on the row's own widths, and the rule is simple: the lane is
the side that **changes**, never the side a value is read from. Read-only
actions - comparing, pairing, refusing to pair - stay with the sentence.

**The count.** "3 out of sync" over six rows. The chip skipped pairs whose
comparison came back `!designDiffers`; the filter kept every pair with a
staleness flag. Three of his six were compared, same design, different name
inside the file - so they left the number and stayed in the list. Same shape as
"0 unpaired" over two rows, and the same rule: a count is the length of its own
list. Both now ask `isOutOfSync`, and the settled test is `identical` - contents,
metadata and name - because a pair that still needs its name written is work,
not noise.

Driven through the real renderer, with each button's lane read back out of the
HTML rather than assumed.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
CSS = ROOT / "web" / "assets" / "wd-tools.css"
NODE_TIMEOUT_S = 120

PROGRAM = r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
function cut(from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return src.slice(a, b);
}
const WD = { esc: s => String(s == null ? '' : s).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])) };
WD.escAttr = WD.esc;
WD.escJsStr = s => String(s == null ? '' : s).replace(/['\\]/g, '\\$&');
function e(s){return WD.esc(s);} function a(s){return WD.escAttr(s);}
function j(s){return WD.escJsStr(s);}
function pj(s){return j(String(s==null?'':s).replace(/\\/g,'/'));}
let currentTab = 'projects';
let activeFilter = 'all';
function rowIsBusy() { return null; }
function fmtRelDate(t) { return String(t); }
globalThis.data = { currentUser: 'me@example.com' };
const navigator = { platform: 'Win32' };

eval(cut('function comparisonIsSettled(', '\nfunction _isExternal(')
   + cut('const PULLABLE_MATCH_TYPES', '\nfunction rowDetailHtml(')
   + cut('const ICONS = {', '\nfunction ic(')
   + 'function ic(n,c){return ICONS[n]?"<svg></svg>":"";}\n'
   + cut('function rdAction(', '\n/* What is inside this site')
   + cut('function rowDetailHtml(', '\nfunction gutCell(')
   /* cloud.js declares its own `_compareResults` inside the first slice, which
      shadows anything declared out here. Reach into the eval scope. */
   + '\nglobalThis.__setCmp = (k, v) => _compareResults.set(k, v);'
   + '\nglobalThis.__key = _compareKey;'
   + '\nglobalThis.__isOutOfSync = isOutOfSync;');

const SITE = 'ABCD1 - AB-99 - 100 Example Road, Anytown, Example State 0000';
function mk(name, extra, cmp, staleness) {
  const cloud = { id: 'c-' + name, name: SITE + ' - ' + name, mtime: 200,
                  owner: 'me@example.com', meta: '4 MB' };
  const local = { name: SITE + ' - ' + name, mtime: 100, meta: '4 MB',
                  path: 'D:/E/' + SITE + '/' + name + '.esx' };
  const r = Object.assign({ status: 'synced', kind: 'projects', matchType: 'id',
                            staleness: staleness || null, cloud, local }, extra || {});
  if (cmp) globalThis.__setCmp(globalThis.__key(cloud.id, local.path), cmp);
  return r;
}

/* Which lane did each button land in? Read out of the rendered band. */
function lanes(html) {
  const cloudLane = html.split('<span class="rd-gut">')[0];
  const localLane = html.split('rd-lane local">')[1] || '';
  const labels = s => (s.match(/<span>([^<]+)<\/span><\/button>/g) || [])
    .map(x => /<span>([^<]+)<\/span>/.exec(x)[1]);
  return { cloud: labels(cloudLane), local: labels(localLane) };
}

const out = {};

/* The reported row: design proven the same, only the name inside the file is
   stale. This is the one that carries `Set the name inside the file to match`. */
out.nameInsideFile = lanes(rowDetailHtml(mk('Power Level Adjustment', {},
  { identical: false, designDiffers: false, nameState: 'internal_only',
    summary: 'Same design.' }, 'cloud_newer'), false));

/* Cloud is genuinely newer: downloading overwrites the local file. */
out.cloudNewer = lanes(rowDetailHtml(mk('Warehouse', {},
  { identical: false, designDiffers: true, summary: 'Real changes.' },
  'cloud_newer'), false));

/* Local is newer: replacing deletes and re-uploads the cloud project. */
out.localNewer = lanes(rowDetailHtml(mk('Vee Three', {},
  { identical: false, designDiffers: true, summary: 'Real changes.' },
  'local_newer'), false));

/* Names disagree: one button renames each side. */
out.mismatch = lanes(rowDetailHtml((() => {
  const r = mk('Temp Trailer', { status: 'mismatch', matchType: 'exact' });
  r.local.name = SITE + ' - Temp Trailer v2';
  return r;
})(), false));

/* One side only. */
out.cloudOnly = lanes(rowDetailHtml({ status: 'orphan', kind: 'projects',
  cloud: { id: 'x', name: SITE + ' - Predictive', mtime: 9, meta: '2 MB',
           owner: 'me@example.com' }, local: null }, false));
out.localOnly = lanes(rowDetailHtml({ status: 'orphan', kind: 'projects',
  cloud: null, local: { name: SITE + ' - Loose', path: 'D:/E/x.esx',
                        mtime: 9, meta: '1 MB' } }, false));

/* Nothing that writes may sit in a lane without declaring which side. */
const everyBand = [out.nameInsideFile, out.cloudNewer, out.localNewer,
                   out.mismatch, out.cloudOnly, out.localOnly];
out.laneCounts = everyBand.map(b => b.cloud.length + b.local.length);

/* --- The count and the list ask one question. ---------------------------- */
const settled = mk('Settled', {},
  { identical: true, designDiffers: false, nameState: 'same' }, 'cloud_newer');
/* "No design change - only bookkeeping differs (dates, revision history)."
   Not identical, and not a decision either: there is no button on that row. */
const bookkeeping = mk('Bookkeeping', {},
  { identical: false, designDiffers: false, nameState: 'same' }, 'cloud_newer');
const nameOnly = mk('NameOnly', {},
  { identical: false, designDiffers: false, nameState: 'internal_only' }, 'cloud_newer');
const real = mk('Real', {}, { identical: false, designDiffers: true }, 'local_newer');
const uncompared = mk('Uncompared', {}, null, 'cloud_newer');
const current = mk('Current', {}, null, null);

out.outOfSync = {
  settled: globalThis.__isOutOfSync(settled),
  bookkeeping: globalThis.__isOutOfSync(bookkeeping),
  nameOnly: globalThis.__isOutOfSync(nameOnly),
  real: globalThis.__isOutOfSync(real),
  uncompared: globalThis.__isOutOfSync(uncompared),
  current: globalThis.__isOutOfSync(current),
};

console.log(JSON.stringify(out));
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class AnActionSitsUnderTheSideItChanges(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        r = subprocess.run(["node", "-e", PROGRAM, str(CLOUD_JS)],
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        cls.out = json.loads(r.stdout.strip().splitlines()[-1])

    def test_the_reported_button_is_on_the_local_side(self):
        """It writes the cloud project's name into the local .esx. Nothing
        reaches Ekahau, so nothing about it belongs under the cloud column.

        Which control does that depends on whether the date moved too - the
        narrow one where it did not, "Make them match" where it did, because
        writing the name alone would leave the date behind. The side is the
        property under test, so the assertion is on the side rather than on
        whichever of the two is offered: naming one pins a control rather
        than the rule it is here to demonstrate.
        """
        band = self.out["nameInsideFile"]
        fixes = ("Set the name inside the file to match", "Make them match")
        self.assertTrue(
            any(f in item for f in fixes for item in band["local"]),
            "no control that writes the local file is on the local side: %s"
            % (band,))
        self.assertFalse(
            any(f in item for f in fixes for item in band["cloud"]),
            "a control that writes the local file is under the cloud column: "
            "%s" % (band,))

    def test_a_download_is_on_the_local_side(self):
        """Downloading replaces the file on disk."""
        self.assertTrue(any("download" in x.lower() for x in self.out["cloudNewer"]["local"]),
                        self.out["cloudNewer"])
        self.assertFalse(any("download" in x.lower() for x in self.out["cloudNewer"]["cloud"]))

    def test_replacing_the_cloud_copy_is_on_the_cloud_side(self):
        """This one deletes and re-uploads the cloud project, so the left lane
        is right - and it is the reason the rule is "the side it changes"
        rather than "actions go right"."""
        self.assertTrue(any("replace cloud" in x for x in self.out["localNewer"]["cloud"]),
                        self.out["localNewer"])
        self.assertEqual([], self.out["localNewer"]["local"])

    def test_each_rename_sits_under_the_name_it_changes(self):
        """The clearest case: two buttons, opposite directions, same row."""
        band = self.out["mismatch"]
        self.assertTrue(any("Cloud" in x and "Local" in x for x in band["local"]))
        self.assertTrue(any("Cloud" in x and "Local" in x for x in band["cloud"]))
        # Cloud → Local writes the local file; Local → Cloud writes the cloud.
        self.assertTrue(any(x.startswith("Cloud") for x in band["local"]), band)
        self.assertTrue(any(x.startswith("Local") for x in band["cloud"]), band)

    def test_download_creates_a_local_file_and_upload_creates_a_cloud_one(self):
        self.assertIn("Download", self.out["cloudOnly"]["local"])
        self.assertIn("Upload", self.out["localOnly"]["cloud"])

    def test_a_read_only_action_stays_with_the_sentence(self):
        """Comparing changes neither side, so it has no side. Putting it in a
        lane would say it writes there."""
        for key in ("nameInsideFile", "cloudNewer", "localNewer"):
            band = self.out[key]
            checks = [x for x in band["cloud"] + band["local"]
                      if x in ("Re-check", "Check what differs")]
            self.assertTrue(checks, f"{key} offered no comparison at all")
            for label in checks:
                self.assertIn(label, band["cloud"],
                              f"{key}: {label} changes nothing and belongs with the sentence")

    def test_every_band_actually_drew_some_buttons(self):
        """A band that rendered empty would pass every assertion above by
        saying nothing."""
        for n in self.out["laneCounts"]:
            self.assertGreater(n, 0)


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class TheCountIsTheLengthOfItsOwnList(AnActionSitsUnderTheSideItChanges):
    """Same probe, the other half of the report."""

    def test_a_pair_that_still_wants_a_click_is_out_of_sync(self):
        """The three rows that vanished from his count. The design matches, but
        the name inside the file does not, and that is the row carrying
        `Set the name inside the file to match` - work, not noise."""
        self.assertTrue(self.out["outOfSync"]["nameOnly"])

    def test_a_pair_whose_only_difference_is_bookkeeping_is_not(self):
        """The regression this predicate caused the day it was widened.

        "I ran the comparison and now it looks like that file is the same
        project and yet it still says 1 of 3 files needs a decision." The row
        said "No design change - only bookkeeping differs (dates, revision
        history)" and offered no action at all, because there is none: nothing
        to click, nothing to choose. A count that calls that a decision is
        asking for something it cannot name."""
        self.assertFalse(self.out["outOfSync"]["bookkeeping"])

    def test_a_pair_proven_identical_is_not(self):
        """Contents, metadata and name all agree - the row itself says
        "Nothing to do". This is what stops a fleet rename reading 29."""
        self.assertFalse(self.out["outOfSync"]["settled"])

    def test_a_real_difference_and_an_uncompared_one_both_count(self):
        self.assertTrue(self.out["outOfSync"]["real"])
        self.assertTrue(self.out["outOfSync"]["uncompared"])

    def test_a_pair_with_no_date_difference_is_never_out_of_sync(self):
        self.assertFalse(self.out["outOfSync"]["current"])


class TheBandBorrowsTheRowsColumns(unittest.TestCase):
    """The lanes are the row's cells, not an approximation of them.

    Written as a property of the stylesheet because the numbers are the defect:
    the band was given a 140px gutter while the row's had grown to 152, so its
    divider sat two pixels off at desktop and ten off below 1100px. Both sides
    read one token now, and nothing may reintroduce a literal.
    """

    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8")

    def _block(self, selector):
        i = self.css.index(selector)
        return self.css[i:self.css.index("}", i)]

    def test_the_gutter_is_one_token(self):
        for selector in (".lr-gut {", ".row-detail .rd-gut {"):
            self.assertIn("var(--ledger-gutter)", self._block(selector),
                          f"{selector} does not use the shared gutter width")

    def test_the_lane_uses_the_cells_own_padding(self):
        """Equal widths are not enough: the row's cloud cell carries the child
        indent and its local cell does not, so lanes that merely split the
        width evenly land the divider somewhere else entirely."""
        lane = self._block(".row-detail .rd-lane.cloud {")
        self.assertIn("var(--ledger-child-indent)", lane)
        self.assertIn("var(--ledger-cell-pad-x)", lane)

    def test_every_gutter_in_the_ledger_reads_the_token(self):
        """A second copy of the number is how the first drift happened, and
        there were six of them: the row's, the tree child's, the header's, the
        A-Z band's, the band's, and a responsive override. Checked by finding
        every ledger rule that sets a gutter width, rather than by naming the
        numbers - a seventh copy at some new value would pass that."""
        import re
        gutters = re.findall(
            r"(\.(?:lr-gut|rd-gut|lh-gut|glh-gap)[^{}]*\{[^}]*\})", self.css)
        self.assertGreaterEqual(len(gutters), 4, "found no gutter rules at all")
        sets_width = re.compile(r"flex(?:-basis)?\s*:")
        checked = 0
        for rule in gutters:
            body = rule[rule.index("{"):]
            if not sets_width.search(body):
                continue   # `flex-wrap` and friends say nothing about width
            checked += 1
            self.assertIn("var(--ledger-gutter)", body,
                          f"a ledger gutter sets its own width: {rule.strip()}")
        self.assertGreaterEqual(checked, 4, "no gutter rule set a width at all")
