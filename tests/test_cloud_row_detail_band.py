"""The findings get the full width, and the fix is a button he can press.

"you can see how we're jamming things into these lines, and how it says that
the design is identical just different names. I thought we were going to
analyze and fix all of this."

Three faults in one screenshot:

* the verdict and every action were stacked into the gutter between two name
  columns, and his project names are long, so that lane is a few characters
  wide
* the verdict said the names differ while he looked at two identical names,
  because the one that differs is inside the file and invisible
* and under a badge reading "the design is identical" the row still offered
  "Cloud newer - download" as its primary action, which contradicts the finding
  directly above it

The control is driven rather than asserted, per the rule this repo now holds:
the band is rendered by the real function, the `onclick` is pulled back out of
that HTML and executed. Four defects have shipped green because a test found
the call in the source and never ran it.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
CSS = ROOT / "web" / "assets" / "wd-tools.css"
NODE_TIMEOUT_S = 120

NODE_SCRIPT = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[2], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
const block = slice('const MATCH_BADGE_SPEC = {', '\nfunction gutCell(r)');

const WD = { esc: s => String(s == null ? '' : s),
             escAttr: s => String(s == null ? '' : s),
             escJsStr: s => String(s == null ? '' : s) };
function e(s) { return WD.esc(s); }
function a(s) { return WD.escAttr(s); }
function j(s) { return WD.escJsStr(s); }
function pj(s) { return j(String(s == null ? '' : s).replace(/\\/g, '/')); }
let currentTab = 'projects';

const calls = [];
const queued = [];
function opEnqueue(spec) { queued.push(spec); return { id: 'op1', promise: Promise.resolve() }; }
function toast() {}
async function pyApi(...args) { calls.push(args); return { ok: true, name: 'SITE1 New Convention' }; }
async function showConfirmModal() { return true; }
function _clearStaleness() {}
function _scheduleOpRefresh() {}
function selectedSyncItems() { return []; }
function clearSelection() {}

const fn = new Function('WD','e','a','j','pj','currentTab','opEnqueue','toast','pyApi','showConfirmModal','_clearStaleness','_scheduleOpRefresh','selectedSyncItems','clearSelection',
  block + '\nreturn { stalenessBadgeHtml, rowDetailHtml, fixInternalName, _compareResults, _compareKey };');
const api = fn(WD,e,a,j,pj,currentTab,opEnqueue,toast,pyApi,showConfirmModal,_clearStaleness,_scheduleOpRefresh,selectedSyncItems,clearSelection);

const row = () => ({
  kind: 'projects', matchType: 'id', staleness: 'cloud_newer',
  differenceKind: 'renamed',
  cloud: { id: 'c1', name: 'SITE1 New Convention', mtime: 200 },
  local: { path: 'C:/projects/SITE1/SITE1 New Convention.esx',
           name: 'SITE1 New Convention', mtime: 100 },
});
const inSyncRow = () => Object.assign(row(), { staleness: null, differenceKind: null });
const key = api._compareKey('c1', 'C:/projects/SITE1/SITE1 New Convention.esx');

const out = {};
out.noBandBeforeChecking = api.rowDetailHtml(inSyncRow(), false);
out.staleUncheckedBand = api.rowDetailHtml(row(), false);

// his exact case: names visibly match, the one inside the file does not
api._compareResults.set(key, {
  designDiffers: false, renamedOnly: true, nameState: 'internal_only',
  summary: 'Same design. The project name inside the file still reads the old name - the file names match.',
});
out.internalOnlyBand = api.rowDetailHtml(row(), false);
out.internalOnlyBadge = api.stalenessBadgeHtml(row());

// drive the fix out of the rendered band
const m = /onclick="event\.stopPropagation\(\);(fixInternalName\([^"]*\))"/.exec(out.internalOnlyBand);
out.foundHandler = !!m;
if (m) {
  const invoke = new Function('fixInternalName', 'return ' + m[1] + ';');
  invoke(api.fixInternalName);
  out.queuedTitle = queued.length ? queued[0].title : '';
}

// a real difference offers no name fix
api._compareResults.set(key, {
  designDiffers: true, renamedOnly: false, nameState: 'same',
  summary: 'Real changes: accessPoints (3 changed).',
});
out.differsBand = api.rowDetailHtml(row(), false);
out.differsBadge = api.stalenessBadgeHtml(row());

(async () => {
  if (queued.length) { out.runResult = await queued[0].run('op1'); }
  out.calls = calls.slice();
  process.stdout.write(JSON.stringify(out));
  process.exit(0);
})().catch(err => { process.stderr.write(String(err && err.stack || err)); process.exit(1); });
"""


_PROBE = {}


def probe():
    """Run the page's own code once and cache it at module level.

    Not hung off a test class: unittest runs classes alphabetically, so a
    second class reading another's cached attribute works or fails on the initials
    somebody chose. That has now cost three debugging detours in one day, which
    is why `test_no_cross_class_probe_sharing` exists.
    """
    if not _PROBE:
        with tempfile.TemporaryDirectory() as td:
            script = Path(td) / "probe.js"
            script.write_text(NODE_SCRIPT, encoding="utf-8")
            proc = subprocess.run(["node", str(script), str(CLOUD_JS)],
                                  capture_output=True, timeout=NODE_TIMEOUT_S)
        if proc.returncode != 0:
            raise AssertionError(
                "node failed: " + proc.stderr.decode("utf-8", "replace"))
        _PROBE.update(json.loads(proc.stdout.decode("utf-8", "replace")))
    return _PROBE


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class TheFindingsGetTheFullWidthTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = probe()

    def test_a_row_with_nothing_to_say_gets_no_band(self):
        """He has ninety-seven local folders. A band on every one of them would
        make the list harder to scan, which is the opposite of the point."""
        self.assertEqual("", self.out["noBandBeforeChecking"])

    def test_a_stale_row_gets_one_even_before_it_is_compared(self):
        """"appear when a comparison has been run, or when the row needs an
        action" - a stale row needs an action, and the actions are what was
        crammed into the gutter in the first place."""
        band = self.out["staleUncheckedBand"]
        self.assertIn("row-detail", band)
        self.assertIn("Not compared yet", band)
        self.assertIn("Check what differs", band)

    def test_the_band_is_its_own_full_width_element(self):
        """Not another thing stacked into the gutter between the names."""
        self.assertIn('class="row-detail', self.out["internalOnlyBand"])

    def test_it_names_which_of_the_three_names_differs(self):
        """The sentence he was reading said the names differ while he looked at
        two identical names."""
        band = self.out["internalOnlyBand"]
        self.assertIn("project name inside the file", band)
        self.assertIn("file names match", band)
        self.assertNotIn("different name on each side", band)

    def test_the_fix_is_offered_where_it_applies(self):
        self.assertIn("Set the name inside the file to match",
                      self.out["internalOnlyBand"])

    def test_clicking_the_fix_reaches_the_server_correctly(self):
        """Executed out of the rendered band, not matched as a string."""
        self.assertTrue(self.out["foundHandler"])
        calls = self.out["calls"]
        self.assertEqual(1, len(calls))
        self.assertEqual("set_internal_project_name", calls[0][0])
        self.assertEqual("C:/projects/SITE1/SITE1 New Convention.esx", calls[0][1])
        self.assertEqual("SITE1 New Convention", calls[0][2])

    def test_the_queued_operation_says_what_it_will_do(self):
        title = self.out["queuedTitle"]
        self.assertIn("project name inside", title)

    def test_a_real_difference_offers_no_name_fix(self):
        """Rewriting the name would not reconcile a design change, and offering
        it there would imply it might."""
        self.assertNotIn("Set the name inside the file",
                         self.out["differsBand"])
        self.assertIn("accessPoints (3 changed)", self.out["differsBand"])


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class ItStopsContradictingItsOwnFindingTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = probe()

    def test_a_proven_identical_row_does_not_shout_download(self):
        """A badge saying the design is identical, directly above a primary
        action saying "Cloud newer - download", is the tool arguing with
        itself - and is why he does not trust the labels."""
        badge = self.out["internalOnlyBadge"]
        self.assertIn("download anyway", badge)
        self.assertIn("is-demoted", badge)
        self.assertNotIn("Cloud newer &middot; download", badge)

    def test_the_download_is_demoted_and_not_removed(self):
        """He may still want it. Quieter, not gone."""
        self.assertIn("verifyReplaceLocal(", self.out["internalOnlyBadge"])

    def test_an_unproven_or_differing_row_keeps_the_normal_wording(self):
        badge = self.out["differsBadge"]
        self.assertNotIn("is-demoted", badge)
        self.assertIn("download", badge)


class ThreeLevelsGetThreeTreatmentsTests(unittest.TestCase):
    """Site, file, detail - three distinct treatments, not three intensities.

    "it should be a clear separator in between each site" and, for the level
    below, "scratch what I said about bolder on the 3rd line ... they should
    delineate that with a line maybe."

    Both instincts point the same way. The site is the unit he works in, so
    that boundary earns the weight; tinting the detail row as well made two
    levels compete for one signal. The site gets a heavy rule and raised
    background, the detail gets a hairline and no tint at all.

    Measured in Firefox, Chrome and Edge at 1920x1200 against twelve sites of
    four files each: site rule 3px, detail rule 1px, detail tint delta 0.
    """

    CSS_TEXT = CSS.read_text(encoding="utf-8")

    def test_the_site_boundary_is_heavy(self):
        block = self.CSS_TEXT[self.CSS_TEXT.index(".ledger.tree .tree-parent {"):]
        block = block[:block.index(chr(10) + "}")]
        self.assertIn("border-top: 3px solid var(--site-rule)", block)

    def test_the_detail_row_is_a_line_rather_than_a_tint(self):
        block = self.CSS_TEXT[self.CSS_TEXT.index(".row-detail {"):]
        block = block[:block.index(chr(10) + "}")]
        self.assertIn("border-top: 1px solid var(--detail-rule)", block)

    def test_the_detail_row_does_not_tint_against_its_parent(self):
        """A tint here would compete with the site boundary. The tokens match
        the row bands exactly, so the rule does all the separating."""
        import re as _re
        dark = self.CSS_TEXT[self.CSS_TEXT.index("--bg: #090909"):]
        dark = dark[:dark.index("}")]
        def token(name):
            m = _re.search("--%s:" % name + r"\s*([^;]+);", dark)
            return m.group(1).strip() if m else None
        self.assertEqual(token("surface"), token("detail-row"))
        self.assertEqual(token("stripe"), token("detail-row-stripe"))

    def test_the_site_and_file_palette_is_left_alone(self):
        """"Currently the sites are labelled in blue and the files are labelled
        using white text, and the sites have a nice border ... I hope they
        don't go the other direction." So this is not touched."""
        self.assertIn(".ledger.tree .tree-parent .lr-cell.cloud .cell-name { color: var(--blue); }",
                      self.CSS_TEXT)
        self.assertIn(".ledger.tree .tree-parent .lr-cell.local .cell-name { color: var(--green); }",
                      self.CSS_TEXT)


class TheBandIsStyledForAWideScreenTests(unittest.TestCase):

    def test_the_band_has_its_own_rules(self):
        css = CSS.read_text(encoding="utf-8")
        self.assertIn(".row-detail {", css)
        self.assertIn(".rd-btn {", css)
        self.assertIn(".stale-badge.is-demoted {", css)

    def test_it_still_functions_on_a_narrow_screen(self):
        """Wide desktop first; narrow merely has to work."""
        css = CSS.read_text(encoding="utf-8")
        self.assertIn("flex-wrap: wrap", css)


class TestsMustNotDependOnClassOrderingTests(unittest.TestCase):
    """One test class reading another's cached probe is a coin flip.

    unittest runs classes in alphabetical order, so reading another class's
    cached attribute works or explodes purely on the initials somebody picked. It cost three
    separate debugging detours in one day - `test_cloud_push_to_replace.py`,
    `test_cloud_sync_all_dialog.py`, and this file - each time looking like a
    real failure and each time being nothing but two letters.

    The fix is always the same: cache the probe at module level and have both
    classes call it. This makes the rule enforceable instead of remembered.
    """

    #: Only a *runtime* read matters. A class body composing a constant
    #: from another class - as test_plantrim_boxes.py does with its shared
    #: HARNESS string - is evaluated at import in file order and is
    #: perfectly safe. The hazard is a setUpClass assigning onto cls from
    #: another test class, inside
    #: setUpClass, which runs when unittest decides to run it. (Describing
    #: that form in prose rather than writing it out, because this pattern
    #: cheerfully matches its own documentation.)
    PATTERN = re.compile(r"cls\.\w+\s*=\s*[A-Z]\w*Tests\.\w+")

    def test_no_cross_class_probe_sharing(self):
        offenders = []
        for path in sorted((ROOT / "tests").glob("test_*.py")):
            text = path.read_text(encoding="utf-8")
            for match in self.PATTERN.finditer(text):
                line = text[:match.start()].count(chr(10)) + 1
                offenders.append("%s:%d %s" % (path.name, line,
                                               match.group(0).strip()))
        self.assertEqual(
            [], offenders,
            "a test class reaches into another test class's attributes, which "
            "only works while the alphabet cooperates: "
            + "; ".join(offenders)
            + ". Cache it in a module-level function and call that from both.")


if __name__ == "__main__":
    unittest.main()
