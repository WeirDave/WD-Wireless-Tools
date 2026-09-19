"""Sync as a per-file judgement, not a direction you pick.

The first attempt at this was "pull everything newer off the cloud". That is a
directional instrument: it happens to be safe, but its safety depends on the
person pressing it having reasoned correctly about which files are where. He
asked for the opposite - the tool already knows, per file, which side is newer,
so it should act on that and remove the opportunity to get it wrong.

What the tool is for shapes the rest. Cloud Manager exists to serve a round
trip: a site starts as DWGs, becomes a local .esx, goes through PlanTrim and
Quick Walls and Ekahau, and ends up in the cloud. Local is where the work
happens and is also his backup of what the cloud holds.

So:
  - each file moves in the direction its dates say, or not at all
  - a newer local file is never replaced by an older cloud one, ever
  - a newer local file is the *normal* result of a day's work, so it is
    reported as still needing to go up rather than quietly counted as done

That last one matters most. The upload direction does not exist yet, so a run
can only ever finish half the loop, and letting him believe he is in sync when
he is not is worse than telling him he is not.

Driven through the real syncEverythingPlan in Node.
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

NODE_PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
// See the note in test_cloud_sync_plan.py: the planner asks the row's
// question now, and the sets that answer it sit above the slice.
const ca = source.indexOf('const PULLABLE_MATCH_TYPES');
const cb = source.indexOf('function canPushToCloud(');
if (ca < 0 || cb < 0) throw new Error('the match-type sets moved');

const a = source.indexOf('function syncEverythingPlan() {');
const b = source.indexOf('function _syncRowsHtml(');
if (a < 0 || b < 0) throw new Error('the planner moved');
// A push ends in a cloud delete, and Ekahau allows that only to the owner, so
// the planner asks `iOwn` exactly as the row does. Sliced in, not stubbed.
const oa = source.indexOf('function ownershipBlock(');
const ob = source.indexOf('\nfunction _isExternal(');
if (oa < 0 || ob < 0) throw new Error('the ownership helpers moved');
// One evaluation, not two: `const` is block-scoped to its own eval, so
// splitting these leaves the planner unable to see the sets.
eval(source.slice(oa, ob) + source.slice(ca, cb) + source.slice(a, b));

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
// A matched file pair. A site's local side would be a folder, not an .esx.
// See the note on the same helper in test_cloud_sync_plan.py.
function pair(name, staleness, matchType) {
  return {
    cloud: { id: 'c-' + name, name: name, mtime: 200 },
    local: { name: name, path: '/local/' + name + '.esx', mtime: 100 },
    matchType: matchType || 'id',
    staleness: staleness || null,
  };
}
function cloudOnly(id) { return { id: id, name: id, mtime: 200 }; }
function names(list, key) { return list.map(x => x[key]).sort().join(','); }
"""


def _run_js(prelude_extra: str, body: str) -> str:
    """Slice a function out of cloud.js, run it, and return what it produced.

    The same pattern the rest of this file uses for the planner, pointed at the
    two pieces that speak to him: the dialog row and the closing toast.
    """
    program = ("""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
function cut(from, to) {
  const a = source.indexOf(from), b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
function e(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, c =>
  ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function fmtRelDate(t) { return String(t == null ? '' : t); }
const said = [];
function toast(msg) { said.push(msg); }
""" + prelude_extra + "\n" + body)
    r = subprocess.run(["node", "-e", program, str(CLOUD_JS)],
                       capture_output=True, text=True, encoding="utf-8",
                       timeout=NODE_TIMEOUT_S)
    if r.returncode != 0:
        raise AssertionError((r.stdout + r.stderr).strip())
    return r.stdout


def _run_push(match_type: str, answer: bool):
    """Call the row's handler with a recording `_enqueuePushLocalOverCloud`.

    This is the control that was asserted-about rather than run for four
    releases while he could not use it, so it is run.
    """
    out = _run_js(
        # `_enqueuePushLocalOverCloud` sits above the handler and is the thing
        # being stubbed, so the slice starts after it.
        "eval(cut('const PULLABLE_MATCH_TYPES', 'function canPushToCloud(')"
        " + cut('async function pushLocalOverCloud(', 'function rowDetailHtml('));",
        "const asked = [], enqueued = [];\n"
        "function _enqueuePushLocalOverCloud(a, b, c, d) { enqueued.push([a,b,c,d]); "
        "return { promise: Promise.resolve() }; }\n"
        "async function showConfirmModal(title, body) { asked.push(body); return "
        + ("true" if answer else "false") + "; }\n"
        "pushLocalOverCloud('c-1', '/l/a.esx', 'a', 'Cloud A', "
        + json.dumps(match_type) + ")\n"
        "  .then(() => console.log(JSON.stringify({ asked, enqueued })));")
    return json.loads(out.strip().splitlines()[-1])


def _render_push_rows(rows):
    """Render the dialog's push table with the real function."""
    out = _run_js(
        "eval(cut('const PULLABLE_MATCH_TYPES', 'function canPushToCloud(')"
        " + cut('function _syncPushRowsHtml(', 'function _syncPickBoxes('));",
        "const html = _syncPushRowsHtml(" + json.dumps(rows) + ");\n"
        "const cells = html.split('</tr>').filter(x => x.indexOf('<tr>') > -1);\n"
        "console.log(JSON.stringify(cells.map(h => "
        "({ checked: / checked/.test(h.split('</td>')[0]), html: h }))));")
    return json.loads(out.strip().splitlines()[-1])


def _run_outcome(results, plan, ran):
    """Run the closing report and return the sentence it says."""
    out = _run_js(
        "eval(cut('function _reportSyncOutcome(', 'if (typeof window'));",
        "_reportSyncOutcome(" + json.dumps(results) + ", " + json.dumps(plan)
        + ", " + json.dumps(ran) + ");\nconsole.log(JSON.stringify(said));")
    return " | ".join(json.loads(out.strip().splitlines()[-1]))


def _js(text: str) -> str:
    return json.dumps(text)


def run_node(checks: str) -> subprocess.CompletedProcess:
    program = NODE_PRELUDE + "eval(" + _js(checks) + ");"
    try:
        return subprocess.run(["node", "-e", program, str(CLOUD_JS)],
                              capture_output=True, text=True,
                              timeout=NODE_TIMEOUT_S)
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(
            f"node did not finish within {NODE_TIMEOUT_S}s. That is a Node "
            f"startup timeout, not a failure of the code under test."
        ) from exc


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class EachFileGoesTheWayItsDatesSay(unittest.TestCase):

    def run_block(self, checks: str):
        result = run_node(checks)
        self.assertEqual(result.returncode, 0,
                         (result.stdout + result.stderr).strip())

    def test_a_mixed_listing_sorts_itself_out_per_file(self):
        """No direction is chosen. Three files, three different answers."""
        self.run_block("""
          data = { summary: {}, matched: [
            pair('cloud-won','cloud_newer'),
            pair('mine','local_newer'),
            pair('agreed', null)] };
          var p = syncEverythingPlan();
          check('the cloud-newer one comes down: ' + names(p.down, 'cloudName'),
                names(p.down, 'cloudName') === 'cloud-won');
          check('the local-newer one is queued to go up: ' + names(p.up, 'cloudName'),
                names(p.up, 'cloudName') === 'mine');
          check('the matching one is left alone entirely',
                p.inSync.length === 1 && p.down.length === 1 && p.up.length === 1);
          done();
        """)

    def test_a_newer_local_file_is_never_in_the_download_set(self):
        """Not a warning he can click through - it simply cannot happen.

        Nothing is copied aside, so his local file is the only copy of whatever
        work is newer than the cloud. Replacing it with an older cloud copy
        would destroy that state outright."""
        self.run_block("""
          data = { summary: {}, matched: [pair('mine','local_newer')] };
          var p = syncEverythingPlan();
          check('never queued for download', p.down.length === 0);
          check('and it is not quietly dropped either', p.up.length === 1);
          done();
        """)

    def test_files_that_already_match_are_not_rewritten(self):
        """Re-running has to be free, because getting current with the cloud
        is a reason to press this on its own."""
        self.run_block("""
          data = { summary: {}, matched: [pair('a', null), pair('b', null)] };
          var p = syncEverythingPlan();
          check('nothing comes down', p.down.length === 0);
          check('nothing goes up', p.up.length === 0);
          check('both counted as matching', p.inSync.length === 2);
          done();
        """)

    def test_it_reaches_files_nested_inside_sites(self):
        """The stale ones are usually inside a site, which is what makes
        assembling this by hand tedious enough to get wrong."""
        self.run_block("""
          data = { summary: {}, matched: [{
            cloud: { id: 'site-1', name: 'Sydney', children: {
              matched: [pair('inner','cloud_newer'), pair('ok', null),
                        pair('worked-on','local_newer')],
              cloudOnly: [cloudOnly('inner-fresh')]
            }},
            local: { name: 'Sydney', path: '/local/Sydney' },
            staleness: null
          }] };
          var p = syncEverythingPlan();
          check('nested stale file found: ' + names(p.down, 'cloudName'),
                names(p.down, 'cloudName') === 'inner');
          check('nested local-newer found: ' + names(p.up, 'cloudName'),
                names(p.up, 'cloudName') === 'worked-on');
          check('nested cloud-only found: ' + names(p.fresh, 'id'),
                names(p.fresh, 'id') === 'inner-fresh');
          check('the in-sync one is counted', p.inSync.length === 1);
          done();
        """)

    def test_a_site_is_never_treated_as_a_file(self):
        """A matched site is the same shape as a matched pair, but its local
        side is a folder - handing that to download-and-replace would point it
        at a directory."""
        self.run_block("""
          data = { summary: {}, matched: [{
            cloud: { id: 'site-1', name: 'Sydney' },
            local: { name: 'Sydney', path: '/local/Sydney' },
            staleness: 'cloud_newer'
          }] };
          var p = syncEverythingPlan();
          check('the folder is not moved', p.down.length === 0);
          done();
        """)

    def test_a_cloud_project_with_no_local_copy_is_fetched(self):
        self.run_block("""
          data = { summary: {}, cloudOnly: [cloudOnly('never-had-it')],
                   orphans: { cloudOnly: [cloudOnly('unfiled')] } };
          var p = syncEverythingPlan();
          check('both are fetched: ' + names(p.fresh, 'id'),
                names(p.fresh, 'id') === 'never-had-it,unfiled');
          done();
        """)

    def test_the_same_project_is_not_queued_twice(self):
        """A project can appear nested under its site and again in the orphan
        list. Two writes racing at one path is a corrupt .esx."""
        self.run_block("""
          data = { summary: {},
            matched: [{
              cloud: { id: 'site-1', name: 'Sydney', children: {
                matched: [pair('dup','cloud_newer')],
                cloudOnly: [cloudOnly('fresh-1')] }},
              local: { name: 'Sydney', path: '/local/Sydney' }, staleness: null
            }],
            cloudOnly: [cloudOnly('fresh-1')],
            orphans: { cloudOnly: [cloudOnly('fresh-1')] } };
          var p = syncEverythingPlan();
          check('one download, not three: ' + p.fresh.length, p.fresh.length === 1);
          check('one update', p.down.length === 1);
          done();
        """)

    def test_a_download_carries_the_site_it_belongs_in(self):
        self.run_block("""
          data = { summary: {}, matched: [{
            cloud: { id: 'site-1', name: 'Sydney', children: {
              matched: [], cloudOnly: [cloudOnly('inner')] }},
            local: { name: 'Sydney', path: '/local/Sydney' }, staleness: null
          }] };
          var p = syncEverythingPlan();
          check('site name travels with it: ' + p.fresh[0].siteName,
                p.fresh[0].siteName === 'Sydney');
          done();
        """)


class ItIsHonestAboutTheHalfItDoesNotDoInBulk(unittest.TestCase):
    """His workload is new sites: build locally from DWGs, work locally, push
    up at the end. So "newer locally" is the normal state of a finished site,
    not an edge case, and counting those as done would be the worst possible
    lie.

    The upload direction exists now - the row has a working
    **Local newer - replace cloud** control. It is deliberately *not* part of
    a bulk run: replacing a cloud project deletes the old one, cloud deletes do
    not come back, and doing sixty of those behind one button is not something
    to offer somebody who has been burned by duplicates twice.

    So the honesty requirement is unchanged and its wording is not. A bulk run
    must still refuse to count these as finished, and must now name the control
    that does finish them instead of saying the direction does not exist."""

    def setUp(self):
        self.source = CLOUD_JS.read_text(encoding="utf-8")
        start = self.source.index("async function syncEverything()")
        self.body = self.source[start:self.source.index("clearSelection();", start)]

    def test_what_is_left_over_is_still_reported(self):
        """The requirement underneath the old wording, which has not changed:
        a run must never let him believe he is in sync when he is not.

        What can be left over has changed. Files going up are in the run, so
        what remains is what he unticked and what cannot move until its pair is
        confirmed - and the closing line names both rather than counting them
        as done."""
        # Run it. What this has to get right is the sentence he reads at the
        # end of a run, and only running it produces the sentence.
        confirmed = _run_outcome(
            {"done": 3, "failed": 0, "skipped": 0},
            {"up": [], "upBlocked": [{}, {}], "downBlocked": [], "inSync": []},
            {"pushed": 0})
        self.assertIn("2 still need the pair confirmed", confirmed)

        unticked = _run_outcome(
            {"done": 1, "failed": 0, "skipped": 0},
            {"up": [{}, {}, {}], "upBlocked": [], "downBlocked": [], "inSync": []},
            {"pushed": 1})
        self.assertIn("2 left unticked and not sent up", unticked)

        finished = _run_outcome(
            {"done": 4, "failed": 0, "skipped": 0},
            {"up": [{}, {}], "upBlocked": [], "downBlocked": [], "inSync": []},
            {"pushed": 2})
        self.assertIn("local and cloud now match", finished)
        self.assertNotIn("still", finished)

    def test_it_no_longer_claims_the_direction_does_not_exist(self):
        """Two sentences that were each true when written and then were not.

        "not built yet" outlived `replace_cloud_project` shipping in v2.104.6.
        "one row at a time" replaced it and outlived the planner being taught
        the same rule in v2.117.0 - and in between it sent him off to press a
        button on each of six files for no reason at all.

        Neither may come back. A limitation described in prose has to be a
        limitation of the operation, not of whichever code path has not caught
        up yet.
        """
        self.assertNotIn("not built", self.body)
        self.assertNotIn("this cannot do it yet", self.body)
        self.assertNotIn("one row at a time", self.body)

    def test_the_files_going_up_are_offered_rather_than_described(self):
        """The whole point: they are in the run now, pickable like everything
        else, and the cloud project each one replaces is on screen."""
        self.assertIn("plan.up.length", self.body)
        self.assertIn("_syncPushRowsHtml(plan.up)", self.body)
        self.assertIn("Replaces this cloud project", self.body)

    def test_a_pair_matched_on_its_name_alone_arrives_unticked(self):
        """Every other section of this dialog arrives ticked. This is the one
        operation in it that deletes something which does not come back, and a
        name-only pair is the one case where "is this the same project" is a
        real question. Ticking it for him would be answering it for him.

        Rendered rather than read: the source can show that *a* condition is
        applied, and only running it shows which row got which answer - which
        is the half that matters when the wrong one deletes a project.
        """
        rows = _render_push_rows([
            {"matchType": "id", "localName": "Proven", "cloudName": "Proven cloud"},
            {"matchType": "exact", "localName": "Guessy", "cloudName": "Guessy cloud"},
            {"matchType": "manual", "localName": "Mine", "cloudName": "Mine cloud"},
        ])
        self.assertEqual([True, False, True],
                         [r["checked"] for r in rows],
                         "the wrong rows are ticked: " + repr(rows))
        # and the one that is not ticked says why, on the row
        self.assertIn("matched by name only", rows[1]["html"])
        self.assertNotIn("matched by name only", rows[0]["html"])
        # every row names the cloud project it would delete
        for r in rows:
            with self.subTest(row=r["html"][:40]):
                self.assertIn("cloud", r["html"])

    def test_the_row_badge_and_the_bulk_run_do_the_same_thing(self):
        """The badge and the Sync confirm disagreed for four releases once
        already, and then disagreed again in a worse way: the row performed the
        operation while the planner called the same file blocked.

        Agreement used to mean the confirm *named* the row's control. It means
        something stronger now - both call the one function that does it, so
        there is no second implementation to drift. That is what stopped this
        being fixable by editing a sentence.
        """
        badge = self.source[self.source.index("function stalenessBadgeHtml"):]
        badge = badge[:badge.index("function gutCell")]
        local_newer = badge[badge.index("if (s === 'local_newer')"):]
        self.assertNotIn("not built", local_newer)
        self.assertIn("pushLocalOverCloud(", local_newer)

        # Run the row's handler against a recording stub rather than reading
        # it. A proven pair goes straight through; a guessed one asks first.
        proven = _run_push("id", answer=True)
        self.assertEqual([["c-1", "/l/a.esx", "a", "Cloud A"]], proven["enqueued"])
        self.assertEqual([], proven["asked"])

        asked = _run_push("exact", answer=True)
        self.assertEqual(1, len(asked["asked"]), "a name-only pair was not asked about")
        self.assertIn("Cloud A", asked["asked"][0],
                      "the question does not name the project it will delete")
        self.assertEqual([["c-1", "/l/a.esx", "a", "Cloud A"]], asked["enqueued"])

        refused = _run_push("exact", answer=False)
        self.assertEqual([], refused["enqueued"], "saying no still ran it")

        # and exactly one place issues the call the operation is made of
        self.assertEqual(1, self.source.count("pyApi('replace_cloud_project'"))

    def test_the_badge_still_says_nothing_is_at_risk_and_what_to_do(self):
        """Being told a direction is missing is only half of it. Sync never
        replaces the newer side with the older one, and the working route is
        Ekahau's own save-to-cloud - which is where the sync-or-overwrite
        prompt he described actually lives."""
        badge = self.source[self.source.index("function stalenessBadgeHtml"):]
        local_newer = badge[badge.index("if (s === 'local_newer')"):
                            badge.index("function gutCell")]
        # Two things still have to be said, and one of them has changed.
        # Nothing is at risk: unchanged. What to do about it: it used to be
        # "save it from Ekahau", because there was nothing else. There is now.
        self.assertIn("newer", local_newer)
        self.assertIn("pushLocalOverCloud(", local_newer)
        self.assertNotIn("save it to the cloud from there", local_newer)

    def test_an_otherwise_clean_run_still_mentions_what_is_waiting(self):
        """Nothing to bring down must not render as "all done" when a
        finished site is still sitting on his machine."""
        head = self.source[self.source.index("async function syncEverything()"):]
        head = head[:head.index("const parts = [];")]
        self.assertIn("plan.up.length", head)
        self.assertIn("to go up", head)
        self.assertNotIn("not built", head)

    def test_the_confirm_says_what_happens_to_the_local_file(self):
        """This sentence has now been wrong twice, both times about a copy.

        It said every generation was kept for ever while retention was deleting
        all but the newest three; a test pinning that phrasing was what held
        the wrong sentence in place for six days. Backups were then removed
        altogether in v2.141.0, and any promise of a copy became untrue rather
        than merely out of date.

        What is true is that the cloud keeps its project when a pull replaces
        the local file, so that is the fact the confirm has to carry - and it
        must not promise a copy on disk that nobody writes.
        """
        self.assertIn("that cloud copy stays there afterwards", self.body)
        for gone in ("nothing is pruned", "newest three per file",
                     ".previous-", "backups folder"):
            self.assertNotIn(gone, self.body.lower().replace("&mdash;", ""),
                             f"the confirm still promises a copy: {gone}")


class NoBluntDirectionalControl(unittest.TestCase):

    def test_the_everyday_button_is_not_directional(self):
        html = CLOUD_HTML.read_text(encoding="utf-8")
        line = next(l for l in html.splitlines() if 'id="syncAllBtn"' in l)
        self.assertIn("syncEverything()", line)
        self.assertNotIn("bulk-btn", line)

    def test_it_promises_it_cannot_overwrite_work(self):
        html = CLOUD_HTML.read_text(encoding="utf-8")
        block = html[html.index('id="syncAllBtn"'):]
        block = block[:block.index("</button>")]
        self.assertIn("never replaces a newer file with an older one", block)

    def test_the_forced_direction_is_labelled_as_an_escape_hatch(self):
        """It may exist - sometimes he really does want the cloud copy - but
        it must not be what he reaches for to get up to date."""
        html = CLOUD_HTML.read_text(encoding="utf-8")
        block = html[html.index('id="bulkVerifyBtn"'):]
        block = block[:block.index("</button>")]
        self.assertIn("Escape hatch", block)
        self.assertIn("Overwrite", block)


class ThereIsStillOneDownloadImplementation(unittest.TestCase):

    def test_it_reuses_the_existing_calls(self):
        source = CLOUD_JS.read_text(encoding="utf-8")
        start = source.index("async function syncEverything()")
        block = source[start:source.index("function _reportSyncOutcome", start)]
        self.assertIn("pyApi('verify_replace_local'", block)
        self.assertIn("pyApi('download_project'", block)


if __name__ == "__main__":
    unittest.main()
