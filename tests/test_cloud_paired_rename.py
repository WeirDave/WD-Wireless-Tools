"""Renaming one side offers to rename the other, and defaults to yes.

    "Did we release the rename functionality where if you're going to rename
    one side or the other it offers to rename the other side so that they keep
    in sync?"

    "If we're going to rename one side or the other then we should ask to
    rename both at the same time ... if they're matching to begin with, then
    renaming one side shouldn't matter to the other side."

He had just renamed every cloud project to his site convention and was working
through a hundred local files by hand to match. This is the offer that stops a
second hundred.

Four things decide whether it is safe, and each has tests here:

* it is only offered for a **matched pair** - an unlinked local file has
  nothing to keep in sync, and an offer to rename a partner that does not
  exist is worse than no offer
* the side he clicked goes **first**, and a failure there stops the pass
  before the partner is touched. Two independent queue items would have gone
  ahead and renamed the other half, turning one failure into a pair that
  disagrees
* a pair that half-renamed **says which half**. "A pair that half-renamed is
  worse than one that didn't, because he'd believe they match."
* it goes through the **ops queue**, which serialises writes to his live cloud

The live cloud path is not exercised anywhere in this file, or anywhere in the
suite. `pyApi` is the boundary and it is stubbed. Every name here is invented.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = (ROOT / "web" / "assets" / "js" / "cloud.js").read_text(encoding="utf-8")
CLOUD_HTML = (ROOT / "web" / "cloud.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "assets" / "wd-tools.css").read_text(encoding="utf-8")

NODE_TIMEOUT_S = 120


def body(name: str) -> str:
    """The source of one function, by name."""
    fn = CLOUD_JS[CLOUD_JS.index("function %s(" % name):]
    return fn[:fn.index("\n}")]


# ── Driving the real functions under Node ───────────────────────────
#
# The pieces that decide the pairing and the order of the two writes are
# lifted out of cloud.js and run, rather than read. `pyApi` is replaced with a
# recorder, so the calls that would reach his cloud are counted instead of
# made.

HARNESS = r"""
const fs = require('fs');
// argv[1] is this probe; argv[2] is the file under test. Reading
// argv[1] makes the harness search its own source, which finds the
// marker strings and nothing after them.
const src = fs.readFileSync(process.argv[2], 'utf8');

function slice(from, to) {
  const a = src.indexOf(from);
  if (a < 0) throw new Error('missing: ' + from);
  const b = src.indexOf(to, a);
  if (b < 0) throw new Error('missing end: ' + to);
  return src.slice(a, b);
}

// The document the dialog talks to, cut to what these functions touch.
const fields = {};
const els = {};
function el(id, extra) {
  els[id] = Object.assign({ id, value: '', checked: false, hidden: false,
                            textContent: '', innerHTML: '' }, extra || {});
  return els[id];
}
['renameInput', 'renameTitle', 'renameWhat', 'renameSub', 'renameInsert',
 'renamePreview', 'renamePair', 'renamePairBoth', 'renamePairLabel'].forEach(i => el(i));
els.renameInput.setSelectionRange = function () {};
els.renameInput.focus = function () {};
global.document = { getElementById: (id) => els[id] || null };

function e(s) { return String(s == null ? '' : s); }
function a(s) { return String(s == null ? '' : s); }
function np(s) { return String(s == null ? '' : s).replace(/\\/g, '/'); }
function p(s) { return a(np(s)); }
let currentTab = 'projects';
let data = null;
let renameTarget = null;
function showModal() {}
function closeModal() {}
/* The real _renameContainerName comes in with the slice, so only the thing
   it reaches for needs standing in for. Leaving the real one in place means
   the fact block under test is the one that ships. */
function _cloudDetailsById(id) {
  let found = null;
  const walk = (node) => {
    if (found || !node) return;
    if (node.id === id) { found = { obj: node, siteName: node.siteName || '' }; return; }
    const kids = node.children;
    if (!kids) return;
    (kids.matched || []).forEach(p => walk(p.cloud));
    (kids.cloudOnly || []).forEach(walk);
  };
  ((data && data.matched) || []).forEach(p => walk(p.cloud));
  ((data && data.cloudOnly) || []).forEach(walk);
  return found;
}
function _scheduleOpRefresh() { calls.push({ fn: 'refresh' }); }

// Every call that would reach the cloud or the disk, recorded not made.
const calls = [];
let failOn = null;      // { fn, args? } -> returns {error}
function pyApi(fn) {
  const args = Array.prototype.slice.call(arguments, 1);
  calls.push({ fn, args });
  if (failOn && failOn.fn === fn) return Promise.resolve({ error: failOn.error });
  return Promise.resolve({ ok: true });
}

// The queue, stubbed to the shape cloud.js actually uses: it takes a spec,
// runs it, and keeps what came back.
const queued = [];
function opEnqueue(spec) {
  const rec = { title: spec.title, sub: spec.sub, type: spec.type,
                error: null, spec };
  queued.push(rec);
  const promise = Promise.resolve()
    .then(() => spec.run())
    .then(r => { rec.result = r; return r; })
    .catch(err => { rec.error = err.message; });
  return { id: 'op1', promise };
}

eval(slice('function startRename(', '\nasync function confirmRename()')
     + slice('async function confirmRename()', '\nfunction startDelete('));
"""


def run_node(script: str) -> dict:
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node is not installed")
    tmp = ROOT / "tests" / "_paired_rename_probe.js"
    tmp.write_text(HARNESS + script, encoding="utf-8")
    try:
        out = subprocess.run(
            [node, str(tmp), str(ROOT / "web" / "assets" / "js" / "cloud.js")],
            capture_output=True, text=True, timeout=NODE_TIMEOUT_S)
    finally:
        tmp.unlink(missing_ok=True)
    if out.returncode != 0:
        raise AssertionError(out.stderr.strip() or out.stdout.strip())
    return json.loads(out.stdout.strip().splitlines()[-1])


# One matched pair, one local file with no cloud copy, and a matched pair
# whose two sides disagree about their name. All invented.
FIXTURE = """
data = {
  matched: [
    { cloud: { id: 'prj-11', name: 'Riverside Depot' },
      local: { path: 'C:\\\\Surveys\\\\Riverside Depot\\\\Riverside Depot.esx',
               name: 'Riverside Depot' } },
    { cloud: { id: 'prj-22', name: 'Harbour Point Phase 2' },
      local: { path: 'C:/Surveys/Harbour Point/Harbour Point.esx',
               name: 'Harbour Point' } },
  ],
  localOnly: [{ path: 'C:/Surveys/Westgate/Westgate.esx', name: 'Westgate' }],
  cloudOnly: [{ id: 'prj-99', name: 'North Campus' }],
};
"""


class TheOfferOnlyAppearsForALinkedPair(unittest.TestCase):

    def test_a_matched_pair_is_offered_both_ways(self):
        got = run_node(FIXTURE + """
        const out = {};
        startRename('local', 'C:/Surveys/Riverside Depot/Riverside Depot.esx',
                    'Riverside Depot', 'projects');
        out.fromLocal = { shown: !els.renamePair.hidden,
                          checked: els.renamePairBoth.checked,
                          label: els.renamePairLabel.textContent,
                          partner: renameTarget.partner };
        startRename('cloud', 'prj-11', 'Riverside Depot', 'projects');
        out.fromCloud = { shown: !els.renamePair.hidden,
                          checked: els.renamePairBoth.checked,
                          label: els.renamePairLabel.textContent,
                          partner: renameTarget.partner };
        console.log(JSON.stringify(out));
        """)
        self.assertTrue(got["fromLocal"]["shown"])
        self.assertTrue(got["fromLocal"]["checked"], "it has to default to yes")
        self.assertEqual("cloud", got["fromLocal"]["partner"]["side"])
        self.assertEqual("prj-11", got["fromLocal"]["partner"]["idOrPath"])
        self.assertIn("cloud project", got["fromLocal"]["label"])

        self.assertTrue(got["fromCloud"]["shown"])
        self.assertTrue(got["fromCloud"]["checked"])
        self.assertEqual("local", got["fromCloud"]["partner"]["side"])
        self.assertIn("Riverside Depot.esx", got["fromCloud"]["partner"]["idOrPath"])
        self.assertIn(".esx", got["fromCloud"]["label"])

    def test_windows_and_posix_separators_find_the_same_pair(self):
        """The row hands the path back with forward slashes; `data` carries
        whatever the filesystem gave. A pair missed on that difference would
        silently stop offering."""
        got = run_node(FIXTURE + """
        startRename('local', 'C:/Surveys/Riverside Depot/Riverside Depot.esx',
                    'Riverside Depot', 'projects');
        console.log(JSON.stringify({ partner: renameTarget.partner }));
        """)
        self.assertEqual("prj-11", got["partner"]["idOrPath"])

    def test_an_unlinked_local_file_is_not_offered_anything(self):
        got = run_node(FIXTURE + """
        startRename('local', 'C:/Surveys/Westgate/Westgate.esx', 'Westgate', 'projects');
        console.log(JSON.stringify({ shown: !els.renamePair.hidden,
                                     checked: els.renamePairBoth.checked,
                                     partner: renameTarget.partner }));
        """)
        self.assertFalse(got["shown"])
        self.assertFalse(got["checked"])
        self.assertIsNone(got["partner"])

    def test_a_cloud_only_project_is_not_offered_anything(self):
        got = run_node(FIXTURE + """
        startRename('cloud', 'prj-99', 'North Campus', 'projects');
        console.log(JSON.stringify({ shown: !els.renamePair.hidden,
                                     partner: renameTarget.partner }));
        """)
        self.assertFalse(got["shown"])
        self.assertIsNone(got["partner"])

    def test_a_pair_nested_under_a_site_is_found_too(self):
        """On the Sites tab the project pairs hang off a site's children, and
        that is the tab he does most of this from."""
        got = run_node("""
        data = { matched: [{
          cloud: { id: 'site-1', name: 'Riverside Depot', children: { matched: [
            { cloud: { id: 'prj-77', name: 'Riverside Depot' },
              local: { path: 'C:/S/Riverside Depot/Riverside Depot.esx',
                       name: 'Riverside Depot' } }] } },
          local: { path: 'C:/S/Riverside Depot', name: 'Riverside Depot' } }] };
        currentTab = 'sites';
        startRename('cloud', 'prj-77', 'Riverside Depot', 'projects');
        console.log(JSON.stringify({ partner: renameTarget.partner,
                                     label: els.renamePairLabel.textContent }));
        """)
        self.assertIn("Riverside Depot.esx", got["partner"]["idOrPath"])
        self.assertIn(".esx", got["label"])

    def test_a_site_pair_is_offered_as_a_site_not_a_project(self):
        got = run_node(FIXTURE.replace("'projects'", "'sites'") + """
        data = { matched: [{ cloud: { id: 'site-1', name: 'Riverside Depot' },
                             local: { path: 'C:/S/Riverside Depot',
                                      name: 'Riverside Depot' } }] };
        currentTab = 'sites';
        startRename('cloud', 'site-1', 'Riverside Depot', 'sites');
        console.log(JSON.stringify({ label: els.renamePairLabel.textContent,
                                     what: els.renameWhat.innerHTML }));
        """)
        self.assertIn("local folder", got["label"])
        self.assertNotIn(".esx", got["label"])


class BothOutcomesAreOnScreenBeforeItRuns(unittest.TestCase):
    """His standing preference: the evidence visible at rest, no hovering and
    no truncation. The other side is behind the dimmed backdrop too."""

    def test_the_partners_current_name_is_a_labelled_fact(self):
        got = run_node(FIXTURE + """
        startRename('local', 'C:/Surveys/Harbour Point/Harbour Point.esx',
                    'Harbour Point', 'projects');
        console.log(JSON.stringify({ what: els.renameWhat.innerHTML }));
        """)
        self.assertIn("Matching cloud project", got["what"])
        self.assertIn("Harbour Point Phase 2", got["what"])
        self.assertIn("rename-what-partner", got["what"])

    def test_the_preview_shows_a_line_per_side(self):
        got = run_node(FIXTURE + """
        startRename('local', 'C:/Surveys/Riverside Depot/Riverside Depot.esx',
                    'Riverside Depot', 'projects');
        els.renameInput.value = 'Riverside Depot - Validation';
        _renamePreview();
        console.log(JSON.stringify({ html: els.renamePreview.innerHTML }));
        """)
        html = got["html"]
        self.assertEqual(2, html.count("rename-preview-line"))
        # The local side carries its extension and the cloud side does not.
        self.assertIn("Riverside Depot - Validation.esx", html)
        self.assertIn(">Riverside Depot - Validation<", html)
        self.assertIn("Local .esx file", html)
        self.assertIn("Cloud project", html)

    def test_declining_says_what_the_other_side_keeps(self):
        """Saying no has a consequence, and he should read it here rather than
        discover it later from a mismatch badge."""
        got = run_node(FIXTURE + """
        startRename('local', 'C:/Surveys/Harbour Point/Harbour Point.esx',
                    'Harbour Point', 'projects');
        els.renameInput.value = 'Harbour Point Phase 3';
        els.renamePairBoth.checked = false;
        _renamePreview();
        console.log(JSON.stringify({ html: els.renamePreview.innerHTML }));
        """)
        self.assertIn("stays", got["html"])
        self.assertIn("Harbour Point Phase 2", got["html"])

    def test_a_mismatched_pair_shows_both_names_converging(self):
        """The case he is doing by hand a hundred times: two sides that
        disagree, both ending up on the one name."""
        got = run_node(FIXTURE + """
        startRename('local', 'C:/Surveys/Harbour Point/Harbour Point.esx',
                    'Harbour Point', 'projects');
        els.renameInput.value = 'Harbour Point Phase 2';
        _renamePreview();
        console.log(JSON.stringify({ html: els.renamePreview.innerHTML }));
        """)
        self.assertIn("Harbour Point.esx", got["html"])
        self.assertIn("Harbour Point Phase 2", got["html"])
        # The cloud side is already there, so its line says so rather than
        # drawing a rename that is not going to happen.
        self.assertIn("unchanged", got["html"])

    def test_nothing_in_the_preview_is_truncated_by_the_stylesheet(self):
        block = CSS[CSS.index(".rename-preview {"):CSS.index(".rename-preview-from")]
        self.assertIn("overflow-wrap: anywhere", block)
        self.assertNotIn("text-overflow", block)
        self.assertNotIn("white-space: nowrap", block)


class TheOrderOfTheTwoWrites(unittest.TestCase):

    def test_the_side_he_clicked_goes_first(self):
        got = run_node(FIXTURE + """
        startRename('local', 'C:/Surveys/Riverside Depot/Riverside Depot.esx',
                    'Riverside Depot', 'projects');
        els.renameInput.value = 'Riverside Depot - Validation';
        confirmRename();
        setTimeout(() => console.log(JSON.stringify({
          calls: calls.filter(c => /^rename_/.test(c.fn || '')).map(c => c.fn),
          title: queued[0].title, sub: queued[0].sub,
          error: queued[0].error })), 20);
        """)
        self.assertEqual(["rename_local", "rename_cloud"], got["calls"])
        self.assertIsNone(got["error"])
        self.assertIn("both sides", got["title"])

    def test_starting_from_the_cloud_reverses_it(self):
        got = run_node(FIXTURE + """
        startRename('cloud', 'prj-11', 'Riverside Depot', 'projects');
        els.renameInput.value = 'Riverside Depot - Validation';
        confirmRename();
        setTimeout(() => console.log(JSON.stringify({
          calls: calls.filter(c => /^rename_/.test(c.fn || '')).map(c => c.fn) })), 20);
        """)
        self.assertEqual(["rename_cloud", "rename_local"], got["calls"])

    def test_the_cloud_call_gets_the_kind_it_needs(self):
        """A project and a site are different endpoints. Sending one to the
        other is the mistake `rowData`'s hardcoded entityKind would have
        caused, which is why the partner is read off `data`."""
        got = run_node("""
        data = { matched: [{ cloud: { id: 'site-1', name: 'Riverside Depot' },
                             local: { path: 'C:/S/Riverside Depot',
                                      name: 'Riverside Depot' } }] };
        currentTab = 'sites';
        startRename('local', 'C:/S/Riverside Depot', 'Riverside Depot', 'sites');
        els.renameInput.value = 'Riverside Depot North';
        confirmRename();
        setTimeout(() => console.log(JSON.stringify({
          calls: calls.filter(c => c.fn !== 'refresh') })), 20);
        """)
        cloud = [c for c in got["calls"] if c["fn"] == "rename_cloud"][0]
        self.assertEqual("sites", cloud["args"][0])

    def test_declining_renames_only_the_side_he_clicked(self):
        got = run_node(FIXTURE + """
        startRename('local', 'C:/Surveys/Riverside Depot/Riverside Depot.esx',
                    'Riverside Depot', 'projects');
        els.renameInput.value = 'Riverside Depot - Validation';
        els.renamePairBoth.checked = false;
        confirmRename();
        setTimeout(() => console.log(JSON.stringify({
          calls: calls.filter(c => /^rename_/.test(c.fn || '')).map(c => c.fn),
          title: queued[0].title })), 20);
        """)
        self.assertEqual(["rename_local"], got["calls"])
        self.assertNotIn("both sides", got["title"])

    def test_a_partner_already_called_this_is_not_asked_to_rename_itself(self):
        """Half his pairs are mid-migration: the cloud side already carries
        the new name. Asking the cloud to rename a project to its own name is
        a round trip that can only fail."""
        got = run_node(FIXTURE + """
        startRename('local', 'C:/Surveys/Harbour Point/Harbour Point.esx',
                    'Harbour Point', 'projects');
        els.renameInput.value = 'Harbour Point Phase 2';
        confirmRename();
        setTimeout(() => console.log(JSON.stringify({
          calls: calls.filter(c => /^rename_/.test(c.fn || '')).map(c => c.fn),
          sub: queued[0].sub })), 20);
        """)
        self.assertEqual(["rename_local"], got["calls"])
        self.assertIn("already called this", got["sub"])


class AHalfRenamedPairSaysSo(unittest.TestCase):
    """"A pair that half-renamed is worse than one that didn't, because he'd
    believe they match.\""""

    def test_a_failure_on_the_first_side_leaves_the_partner_alone(self):
        """Two independent queue items would have renamed the other half
        anyway, turning one failure into a pair that disagrees."""
        got = run_node(FIXTURE + """
        failOn = { fn: 'rename_local', error: 'Permission denied' };
        startRename('local', 'C:/Surveys/Riverside Depot/Riverside Depot.esx',
                    'Riverside Depot', 'projects');
        els.renameInput.value = 'Riverside Depot - Validation';
        confirmRename();
        setTimeout(() => console.log(JSON.stringify({
          calls: calls.filter(c => /^rename_/.test(c.fn || '')).map(c => c.fn),
          error: queued[0].error })), 20);
        """)
        self.assertEqual(["rename_local"], got["calls"])
        self.assertIn("Nothing was renamed", got["error"])
        self.assertIn("Permission denied", got["error"])

    def test_a_failure_on_the_second_side_names_both_halves(self):
        got = run_node(FIXTURE + """
        failOn = { fn: 'rename_cloud', error: 'Cloud returned 503' };
        startRename('local', 'C:/Surveys/Riverside Depot/Riverside Depot.esx',
                    'Riverside Depot', 'projects');
        els.renameInput.value = 'Riverside Depot - Validation';
        confirmRename();
        setTimeout(() => console.log(JSON.stringify({
          error: queued[0].error })), 20);
        """)
        err = got["error"]
        # Which side landed, what it is now called, which side did not, and
        # what that one is still called.
        self.assertIn("local .esx file is now", err)
        self.assertIn("Riverside Depot - Validation", err)
        self.assertIn("cloud project is still", err)
        self.assertIn("Riverside Depot", err)
        self.assertIn("Cloud returned 503", err)
        self.assertNotIn("Nothing was renamed", err)

    def test_the_list_is_refreshed_even_when_the_second_side_failed(self):
        """Otherwise the row keeps showing the old name for the half that did
        rename, which is the same lie by a different route."""
        got = run_node(FIXTURE + """
        failOn = { fn: 'rename_cloud', error: 'Cloud returned 503' };
        startRename('local', 'C:/Surveys/Riverside Depot/Riverside Depot.esx',
                    'Riverside Depot', 'projects');
        els.renameInput.value = 'Riverside Depot - Validation';
        confirmRename();
        setTimeout(() => console.log(JSON.stringify({
          refreshed: calls.some(c => c.fn === 'refresh') })), 20);
        """)
        self.assertTrue(got["refreshed"])

    def test_retry_finishes_the_pair_rather_than_repeating_it(self):
        """Retrying a rename that already landed would ask the disk to rename
        the file to the name it already has."""
        got = run_node(FIXTURE + """
        failOn = { fn: 'rename_cloud', error: 'Cloud returned 503' };
        startRename('local', 'C:/Surveys/Riverside Depot/Riverside Depot.esx',
                    'Riverside Depot', 'projects');
        els.renameInput.value = 'Riverside Depot - Validation';
        confirmRename();
        setTimeout(() => {
          failOn = null;
          calls.length = 0;
          Promise.resolve().then(() => queued[0].spec.retryFn()).then(() => {
            console.log(JSON.stringify({
              calls: calls.filter(c => /^rename_/.test(c.fn || '')).map(c => c.fn) }));
          });
        }, 20);
        """)
        self.assertEqual(["rename_cloud"], got["calls"])


class ItGoesThroughTheQueue(unittest.TestCase):
    """v2.107.0 made the deck a real queue that serialises writes to his live
    cloud. A rename is exactly that kind of write."""

    def test_neither_path_calls_the_api_outside_an_op(self):
        fn = body("confirmRename")
        self.assertEqual(2, fn.count("opEnqueue("))
        # Every cloud/disk call in there is inside a run/retry closure, never
        # at the top level of confirmRename.
        for line in fn.splitlines():
            stripped = line.strip()
            if stripped.startswith("const first = await _renameOneSide"):
                continue
            self.assertNotRegex(stripped, r"^await pyApi\(")

    def test_the_queue_item_says_it_is_doing_both(self):
        fn = body("confirmRename")
        self.assertIn("Renaming both sides to", fn)
        self.assertIn("sub:", fn)

    def test_the_failing_half_can_be_retried_from_the_deck(self):
        fn = body("confirmRename")
        self.assertIn("retryFn:", fn)
        deck = CLOUD_JS[:CLOUD_JS.index("function opEnqueue(")]
        self.assertIn("op.retryFn", deck)


class TheOfferIsInTheDialogItself(unittest.TestCase):
    """Same standing rule as the rest of this dialog: a modal contains
    everything needed to finish the job, because the backdrop is dimmed."""

    def test_the_toggle_and_its_label_are_in_the_markup(self):
        self.assertIn('id="renamePair"', CLOUD_HTML)
        self.assertIn('id="renamePairBoth"', CLOUD_HTML)
        self.assertIn('id="renamePairLabel"', CLOUD_HTML)
        self.assertIn('checked', CLOUD_HTML[
            CLOUD_HTML.index('id="renamePairBoth"'):
            CLOUD_HTML.index('id="renamePairBoth"') + 200])

    def test_toggling_it_redraws_the_preview(self):
        """Otherwise the two outcomes on screen stop describing what the
        button is about to do."""
        m = re.search(r'id="renamePairBoth"[^>]*data-fn="([^"]+)"', CLOUD_HTML)
        self.assertIsNotNone(m)
        self.assertIn("_renamePreview", m.group(1))

    def test_it_is_styled_to_read_at_rest_rather_than_on_hover(self):
        block = CSS[CSS.index(".rename-pair-toggle {"):]
        block = block[:block.index("}")]
        self.assertNotIn("display: none", block)
        self.assertNotIn("opacity: 0", block)


class TheThirdNameIsBroughtWithThem(unittest.TestCase):
    """There are three names on a row and renaming moved only two of them.

    The file on disk, the project in Ekahau, and `project.name` *inside* the
    .esx. A paired rename changed the first two and left the third, so the
    comparison reported "renamed" the moment it finished - and Ekahau stamps
    `modifiedAt` on its own rename while the local file's internal date does
    not move, so the row read "cloud newer" as well. The feature built to stop
    him hand-matching a hundred pairs left all hundred of them complaining,
    which is what `tools/cloud_realign.py` was then written to clean up.

    `set_internal_project_name` already existed for exactly this, wired to the
    row's own "Set the name inside the file to match". The rename never called
    it.
    """

    def _rename_both(self, extra=""):
        return run_node(FIXTURE + """
        const out = {};
        startRename('local', 'C:/Surveys/Riverside Depot/Riverside Depot.esx',
                    'Riverside Depot', 'projects');
        els.renameInput.value = 'SITE1 Riverside Depot';
        els.renamePairBoth.checked = true;
        """ + extra + """
        confirmRename();
        setTimeout(() => {
          out.calls = calls.filter(c => c.fn).map(c => ({ fn: c.fn, args: c.args }));
          console.log(JSON.stringify(out));
        }, 20);
        """)

    def test_the_name_inside_the_file_is_set_to_match(self):
        got = self._rename_both()
        internal = [c for c in got["calls"]
                    if c["fn"] == "set_internal_project_name"]
        self.assertEqual(1, len(internal),
                         "the name inside the .esx was left as it was: "
                         + repr([c["fn"] for c in got["calls"]]))
        self.assertEqual("C:/Surveys/Riverside Depot/Riverside Depot.esx",
                         internal[0]["args"][0])
        self.assertEqual("SITE1 Riverside Depot", internal[0]["args"][1])

    def test_it_happens_after_both_renames_not_before(self):
        """A failed rename leaves the pair alone, so the third name must not
        move ahead of them."""
        got = self._rename_both()
        order = [c["fn"] for c in got["calls"] if c["fn"] != "refresh"]
        self.assertIn("set_internal_project_name", order, order)
        self.assertLess(order.index("rename_local"),
                        order.index("set_internal_project_name"), order)
        self.assertLess(order.index("rename_cloud"),
                        order.index("set_internal_project_name"), order)

    def test_a_failed_rename_does_not_rewrite_the_file(self):
        got = self._rename_both("failOn = { fn: 'rename_local', error: 'nope' };")
        self.assertNotIn("set_internal_project_name",
                         [c["fn"] for c in got["calls"]],
                         "the file was rewritten for a rename that failed")

    def test_a_site_row_has_no_third_name_to_set(self):
        """A folder and a cloud site have two names, not three."""
        got = run_node(FIXTURE + """
        const out = {};
        startRename('cloud', 'site-1', 'Riverside Depot', 'sites');
        els.renameInput.value = 'SITE1 Riverside Depot';
        confirmRename();
        setTimeout(() => {
          out.calls = calls.filter(c => c.fn).map(c => c.fn);
          console.log(JSON.stringify(out));
        }, 20);
        """)
        self.assertNotIn("set_internal_project_name", got["calls"], got["calls"])


class TheLiveCloudIsNeverTouchedHere(unittest.TestCase):
    """Rule zero's neighbour: his real account is not a test fixture.

    Everything above stops at `pyApi`. Nothing in this file names a real
    project, a real site or a real path, and nothing reaches the network.
    """

    def test_the_probe_file_is_not_left_behind(self):
        self.assertFalse((ROOT / "tests" / "_paired_rename_probe.js").exists())

    def test_every_call_in_these_tests_stops_at_the_stub(self):
        self.assertIn("function pyApi(fn)", HARNESS)
        self.assertNotIn("require('http", HARNESS)
        self.assertNotIn("fetch(", HARNESS)


if __name__ == "__main__":
    unittest.main()
