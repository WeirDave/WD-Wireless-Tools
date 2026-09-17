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
const a = source.indexOf('function syncEverythingPlan() {');
const b = source.indexOf('function _syncRowsHtml(');
if (a < 0 || b < 0) throw new Error('the planner moved');
eval(source.slice(a, b));

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
// A matched file pair. A site's local side would be a folder, not an .esx.
function pair(name, staleness) {
  return {
    cloud: { id: 'c-' + name, name: name, mtime: 200 },
    local: { name: name, path: '/local/' + name + '.esx', mtime: 100 },
    staleness: staleness || null,
  };
}
function cloudOnly(id) { return { id: id, name: id, mtime: 200 }; }
function names(list, key) { return list.map(x => x[key]).sort().join(','); }
"""


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
        """Not a warning he can click through - it simply cannot happen. His
        local copy is both the working file and the backup, so replacing it
        with an older cloud copy can destroy the only copy of a state."""
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

    def test_files_waiting_to_go_up_are_listed_by_name(self):
        self.assertIn("plan.up.length", self.body)
        self.assertIn("local &rarr; cloud", self.body)

    def test_it_no_longer_claims_the_direction_does_not_exist(self):
        """It said "not built yet", which was true and stopped being true.

        `replace_cloud_project` shipped in v2.104.6 and the row now calls it.
        What the bulk confirm has to say changed with it: not that the
        direction is missing, but that it is done one row at a time, and why.
        """
        self.assertNotIn("not built", self.body)
        self.assertNotIn("this cannot do it yet", self.body)
        self.assertIn("one row at a time", self.body)

    def test_the_row_badge_and_the_confirm_still_agree(self):
        """The badge and the Sync confirm disagreed for four releases once
        already, and the badge is the one he reads first because it is on the
        row that prompted the question. They have to move together.

        Now that the row can actually do it, agreement means the confirm points
        at the control rather than contradicting it.
        """
        badge = self.source[self.source.index("function stalenessBadgeHtml"):]
        badge = badge[:badge.index("function gutCell")]
        local_newer = badge[badge.index("if (s === 'local_newer')"):]
        self.assertNotIn("not built", local_newer)
        self.assertIn("pushLocalOverCloud(", local_newer)
        # and the bulk confirm names the same control rather than denying it
        self.assertIn("replace cloud", self.body.lower())

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

    def test_the_run_ends_by_saying_where_the_two_sides_stand(self):
        """"Make sure the two versions are in sync" is a step he does by hand
        at the end of every site; a run should answer it."""
        source = self.source[self.source.index("function _reportSyncOutcome"):]
        source = source[:source.index("if (typeof window")]
        self.assertIn("local and cloud now match", source)
        self.assertIn("still to go up", source)

    def test_where_the_backups_went_is_reported(self):
        """The local copy is his backup of the cloud, so a replaced one has to
        be findable without asking."""
        source = self.source[self.source.index("function _reportSyncOutcome"):]
        source = source[:source.index("if (typeof window")]
        self.assertIn("results.backups", source)
        self.assertIn("previous local cop", source)

    def test_more_than_one_generation_of_backup_survives(self):
        """One generation is not a backup if two runs happen in a row.

        That intent is unchanged; the sentence asserting it had gone stale.
        This used to require the dialog to say "nothing is pruned", which was
        written for v2.86.0 and stopped being true in v2.93.0 the following day,
        when backups got a retention policy. For six days the dialog told him
        every generation was kept for ever while the code was deleting all but
        the newest three, and this test was what held the wrong sentence in
        place.

        So it asserts the property rather than the old phrasing: names are
        timestamped so two runs cannot collide, and retention keeps more than
        one.
        """
        self.assertIn("newest three per file are kept", self.body.lower())
        self.assertNotIn("nothing is pruned", self.body)
        py = (ROOT / "tools" / "cloud_manager.py").read_text(encoding="utf-8")
        block = py[py.index("def verify_replace_local"):]
        block = block[:block.index("\n    def ", 10)] if "\n    def " in block[10:] else block
        # Timestamped, so a second run cannot land on the first one's name.
        # The name is built in `_backup_target` now, which also decides the
        # folder - the copy goes to `<project folder>/backups/` rather than
        # beside the live file.
        self.assertIn("_backup_target(src", block)
        py_all = (ROOT / "tools" / "cloud_manager.py").read_text(encoding="utf-8")
        target = py_all[py_all.index("def _backup_target("):]
        target = target[:target.index("_SKIP_DIRS")]
        self.assertIn('f"{src.stem}.previous-{stamp}{src.suffix}"', target)


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
