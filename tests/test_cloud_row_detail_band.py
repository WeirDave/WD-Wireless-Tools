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
// A row's controls are built from the shared icon helpers, and those sit
// above the badges. Slicing from the badges alone compiles and then throws
// `ic is not defined` on the first render - so the slice starts higher
// rather than the helper being stubbed, because a stub would test the stub.
// `stalenessBadgeHtml` asks `comparisonIsSettled` whether the row has anything
// left to do at all, and that lives above this slice.
const block = slice('function comparisonIsSettled(', '\nfunction isOutOfSync(')
            + slice('const ICONS = {', '\nfunction siteDigest(')
            + slice('const MATCH_BADGE_SPEC = {', '\nfunction gutCell(r)');

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
/* An action redraws its own row now - that is the fix, not an incidental - so
   the probe needs something for it to call, and counts the redraws. */
globalThis.rendered = 0;
function renderRows() { globalThis.rendered++; }
function _scheduleOpRefresh() {}
function selectedSyncItems() { return []; }
function clearSelection() {}

// `renderRows` joined the list because an action redraws its own row now -
// that is the fix rather than a side effect, so the probe supplies one and
// counts the redraws.
const fn = new Function('WD','e','a','j','pj','currentTab','opEnqueue','toast','pyApi','showConfirmModal','_clearStaleness','_scheduleOpRefresh','selectedSyncItems','clearSelection','renderRows',
  block + '\nreturn { stalenessBadgeHtml, rowDetailHtml, fixInternalName, _setRowBusy, _compareResults, _compareKey };');
const api = fn(WD,e,a,j,pj,currentTab,opEnqueue,toast,pyApi,showConfirmModal,_clearStaleness,_scheduleOpRefresh,selectedSyncItems,clearSelection,renderRows);

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

/* The same finding on a pair whose dates already agree.

   `fixInternalName` writes the name and nothing else, which is the whole
   job when there is no date difference to carry over. Where the cloud side
   also reads newer, writing the name alone leaves the date behind and the
   row goes on reporting a difference - so that case offers "Make them
   match", which writes both. Two states, two controls, and this is the one
   the narrower control belongs to. */
out.internalOnlyNotStale = api.rowDetailHtml(
  Object.assign(inSyncRow(), { differenceKind: 'renamed' }), false);

// drive the fix out of the rendered band
const m = /onclick="event\.stopPropagation\(\);(fixInternalName\([^"]*\))"/.exec(out.internalOnlyNotStale);
out.foundHandler = !!m;
if (m) {
  const invoke = new Function('fixInternalName', 'return ' + m[1] + ';');
  invoke(api.fixInternalName);
  out.queuedTitle = queued.length ? queued[0].title : '';
  /* The click has landed, so the row says it is working. Captured here
     because the next render deliberately shows a different state. */
  out.busyBand = api.rowDetailHtml(row(), false);
  api._setRowBusy('c1', 'C:/projects/SITE1/SITE1 New Convention.esx', null);
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
  out.rendered = globalThis.rendered;
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
        # The property, not the sentence: the row says what moved the date and
        # offers the read-only check. Pinning the phrasing pins the wording he
        # could not make sense of along with it.
        self.assertIn("date", band)
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
        """On a pair whose dates agree, the name is the whole difference and
        the narrow control is the whole fix."""
        self.assertIn("Set the name inside the file to match",
                      self.out["internalOnlyNotStale"])

    def test_where_the_date_has_moved_too_the_wider_fix_is_offered(self):
        """"How come we're not fixing the difference, if it's something we
        can identify - like a date, or the internal project number or name?"

        Writing the name alone here would leave the date behind, so the row
        would go on saying the cloud copy is newer and he would be back where
        he started. The control that writes both is the one offered.
        """
        band = self.out["internalOnlyBand"]
        self.assertIn("Make them match", band)
        self.assertNotIn("Set the name inside the file to match", band)

    def test_clicking_the_fix_reaches_the_server_correctly(self):
        """Executed out of the rendered band, not matched as a string."""
        self.assertTrue(self.out["foundHandler"])
        calls = self.out["calls"]
        self.assertEqual("set_internal_project_name", calls[0][0])
        self.assertEqual("C:/projects/SITE1/SITE1 New Convention.esx", calls[0][1])
        self.assertEqual("SITE1 New Convention", calls[0][2])

    def test_and_then_confirms_the_result_without_being_asked(self):
        """"obviously I shouldn't have to recheck twice - once to tell me
        what's wrong and another one after I've done the action."

        He had to, because the row went on showing the state he had just
        changed until a background poll noticed. The action re-compares its own
        pair and renders the answer, so the second check is the tool's job now.
        That is the second server call, and it is the point of the change
        rather than an extra.
        """
        calls = self.out["calls"]
        self.assertEqual(2, len(calls), calls)
        self.assertEqual("compare_with_cloud", calls[1][0])
        #: Both arguments, in the order `API_MAP` maps positionally onto
        #: `['path', 'cloudId']`. Asserting only the second one passed just as
        #: happily while the two were the wrong way round, which is how the
        #: swap in `settlePair` survived from v2.120.0 - one position out of a
        #: pair is not a contract, it pins whichever order it finds. The keys
        #: the server actually reads are asserted in
        #: `tests/test_cloud_settle_names_its_arguments.py`.
        self.assertEqual("C:/projects/SITE1/SITE1 New Convention.esx", calls[1][1])
        self.assertEqual("c1", calls[1][2])
        self.assertGreater(self.out["rendered"], 0,
                           "the row was never redrawn, so he would not see it")

    def test_the_queued_operation_says_what_it_will_do(self):
        title = self.out["queuedTitle"]
        self.assertIn("project name inside", title)

    def test_a_real_difference_offers_no_name_fix(self):
        """Rewriting the name would not reconcile a design change, and offering
        it there would imply it might."""
        self.assertNotIn("Set the name inside the file",
                         self.out["differsBand"])
        self.assertIn("accessPoints (3 changed)", self.out["differsBand"])

    def test_a_row_mid_action_says_so_instead_of_its_old_state(self):
        """"you don't have any idea if it worked or didn't work or did
        something or didn't do something."

        The click has to be visible where he is looking, which is the row - not
        only in the ops deck in the corner.
        """
        self.assertIn("is-busy", self.out["busyBand"])
        self.assertIn("Working", self.out["busyBand"])
        self.assertNotIn("Cloud newer", self.out["busyBand"])


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
        self.assertIn("download anyway", badge.lower())
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

    # `test_the_site_and_file_palette_is_left_alone` was here, asserting that
    # this stylesheet contains two particular `color:` rules - and it is the
    # reason there is now a browser-driven test instead.
    #
    # It went on passing through the whole period the local folder name
    # rendered white, because a later rule in the same file set it back to
    # `--text` and a substring search cannot see a cascade. The string was
    # there and the colour was not. It would also have passed with the token
    # behind it flattened to a value measuring 3.45:1, which is the second
    # half of the same regression.
    #
    # `tests/test_cloud_name_colours.py` renders the real markup with this
    # stylesheet, reads `getComputedStyle` back and computes contrast from
    # the pixels. It fails on both of those and on a file name gaining a
    # colour - the "other direction" the old docstring was quoting.


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
