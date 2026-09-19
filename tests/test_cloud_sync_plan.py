"""Sync has to mean "make these match", not "make these names match".

The reported failure: select three files the badge says are newer on cloud,
press Sync, and nothing comes down. `syncPlan` sorted matched pairs into one
bucket that only ever got renamed, and put *content* transfer solely in the
per-row arrow. Bulk reconciled presence - which files exist, and where - and
never content.

The other half is that the upload direction does not exist at all. The API
client's upload flow creates a new cloud project rather than replacing one in
place, so a locally-newer pair cannot be pushed. That is a real gap, and the
plan has to carry it as its own category so the confirm can name those files
instead of letting a selection of three quietly become an action on two.

Driven through the real syncPlan in Node.
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

NODE_PRELUDE = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[1], 'utf8');
function slice(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
// Both planners now ask the same question the row asks - may this pair
// move in this direction - and the answer is these two sets. They sit
// above the planner, so a slice that starts at the planner throws
// ReferenceError instead of answering. Stubbing them would test the stub.
// One evaluation, not two: `const` is block-scoped to its own eval, so
// splitting these leaves the planner unable to see the sets.
eval(slice('const PULLABLE_MATCH_TYPES', 'function canPushToCloud(')
   + slice('function syncPlan(items, dir) {', 'function selectedSyncItems'));

// Only orphan rows consult this; pairs never reach it.
globalThis.isProjectSyncItem = () => true;

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
// `matchType` defaults to Ekahau's own id, which is what these fixtures have
// always meant by "a matched pair". The planner asks for it now - a pair it
// cannot vouch for is refused in both directions, same as on the row - so
// leaving it undefined would quietly turn every fixture into a guessed pair.
function pair(name, staleness, matchType) {
  return { kind: 'pair', cloudId: 'c-' + name, cloudName: name,
           localName: name, localPath: '/l/' + name + '.esx',
           matchType: matchType || 'id',
           staleness: staleness || null, cloudMtime: 200, localMtime: 100 };
}
const _code = 'code';   // a pairing WD guessed at, never proven
function names(list) { return list.map(d => d.cloudName).sort().join(','); }
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
class SyncMovesContent(unittest.TestCase):

    def run_block(self, checks: str):
        result = run_node(checks)
        self.assertEqual(result.returncode, 0,
                         (result.stdout + result.stderr).strip())

    def test_three_cloud_newer_files_are_three_downloads(self):
        """The reported case, exactly: three selected, three come down."""
        self.run_block("""
          var items = [pair('a','cloud_newer'), pair('b','cloud_newer'),
                       pair('c','cloud_newer')];
          var plan = syncPlan(items, 'to-local');
          check('all three are content transfers, got ' + plan.contentPulls.length,
                plan.contentPulls.length === 3);
          check('and none of them is treated as a rename',
                plan.pairs.length === 0);
          check('the total counts them: ' + plan.total, plan.total === 3);
          done();
        """)

    def test_a_pair_that_is_in_sync_is_still_only_a_rename(self):
        """The old behaviour is not lost - a matched pair whose sides agree in
        age but not in name is exactly what rename is for."""
        self.run_block("""
          var plan = syncPlan([pair('a', null)], 'to-local');
          check('no content moves', plan.contentPulls.length === 0);
          check('it is a rename', plan.pairs.length === 1);
          done();
        """)

    def test_a_locally_newer_pair_is_never_silently_overwritten(self):
        """It must not fall into the pull bucket, and must not be quietly
        dropped either.

        "Blocked" used to be the only answer available, because neither
        direction could send a newer local file up. It is not refused - it is
        simply not this direction's business - so it is reported as `wrongWay`
        and the confirm points at the run that does move it.
        """
        self.run_block("""
          var plan = syncPlan([pair('a','local_newer')], 'to-local');
          check('not pulled down over the newer local file',
                plan.contentPulls.length === 0);
          check('not silently renamed instead', plan.pairs.length === 0);
          check('reported so the confirm can name it',
                plan.wrongWay.length === 1);
          check('not called refused, because it is not',
                plan.blockedPushes.length === 0);
          done();
        """)

    def test_and_the_other_direction_actually_sends_it_up(self):
        """The half of his report that was still broken: "I hit the checkbox
        and I can't sync it either."

        The row has drawn a working Local newer button since v2.104.6 and the
        planner refused the same file, so ticking it and pressing Sync did
        nothing at all.
        """
        self.run_block("""
          var plan = syncPlan([pair('a','local_newer')], 'to-cloud');
          check('planned as a push: ' + plan.contentPushes.length,
                plan.contentPushes.length === 1);
          check('and counted as work: ' + plan.total, plan.total === 1);
          check('not renamed instead', plan.pairs.length === 0);
          done();
        """)

    def test_a_guessed_pairing_is_refused_in_both_directions(self):
        """The row will not overwrite either copy on a pairing WD only guessed
        at - a shared site code, or similar wording. The planner had no such
        test in either direction: it refused every push including the proven
        ones, and permitted every pull including the guessed ones.

        The pull half is the more dangerous of the two. It overwrote a local
        file the row would not have touched.
        """
        self.run_block("""
          var up = syncPlan([pair('a','local_newer',_code)], 'to-cloud');
          check('no push planned', up.contentPushes.length === 0);
          check('and it is named as refused', up.blockedPushes.length === 1);
          var down = syncPlan([pair('b','cloud_newer',_code)], 'to-local');
          check('no pull planned', down.contentPulls.length === 0);
          check('and it is named as refused', down.blockedPulls.length === 1);
          done();
        """)

    def test_a_mixed_selection_reports_both_halves(self):
        """Selecting some of each has to be honest about which is which."""
        self.run_block("""
          var items = [pair('down1','cloud_newer'), pair('down2','cloud_newer'),
                       pair('up1','local_newer'), pair('same', null)];
          var plan = syncPlan(items, 'to-local');
          check('two come down: ' + names(plan.contentPulls),
                names(plan.contentPulls) === 'down1,down2');
          check('one belongs to the other direction: ' + names(plan.wrongWay),
                names(plan.wrongWay) === 'up1');
          check('one is a plain rename: ' + names(plan.pairs),
                names(plan.pairs) === 'same');
          check('the other direction is not counted as this run: ' + plan.total,
                plan.total === 3);

          var back = syncPlan(items, 'to-cloud');
          check('and running it sends that one up: ' + names(back.contentPushes),
                names(back.contentPushes) === 'up1');
          done();
        """)

    def test_pulling_content_is_a_one_way_direction(self):
        """Syncing *to cloud* must not start overwriting local files."""
        self.run_block("""
          var plan = syncPlan([pair('a','cloud_newer')], 'to-cloud');
          check('nothing is pulled when the user asked to push',
                plan.contentPulls.length === 0);
          done();
        """)

    def test_a_matched_site_is_never_treated_as_a_file(self):
        """A matched site is also kind 'pair', but its local side is a folder.
        Handing that to the download-and-replace path would point it at a
        directory."""
        self.run_block("""
          var site = { kind: 'pair', cloudId: 's1', cloudName: 'Building A',
                       localName: 'Building A', localPath: '/l/Building A',
                       staleness: 'cloud_newer', cloudMtime: 200, localMtime: 100 };
          var plan = syncPlan([site], 'to-local');
          check('a folder is not content-transferred',
                plan.contentPulls.length === 0);
          check('it stays an ordinary matched row', plan.pairs.length === 1);
          done();
        """)

    def test_cloud_only_orphans_still_download(self):
        """Presence reconciliation is not regressed by adding content."""
        self.run_block("""
          var orphan = { kind: 'cloud', id: 'x', name: 'x' };
          var plan = syncPlan([orphan], 'to-local');
          check('the orphan is still a download', plan.downloads.length === 1);
          done();
        """)


class TheConfirmNamesWhatItWillDestroy(unittest.TestCase):
    """A bulk overwrite that says "3 files" is not something anyone can check."""

    def setUp(self):
        self.source = CLOUD_JS.read_text(encoding="utf-8")
        start = self.source.index("async function bulkSync(dir)")
        self.body = self.source[start:self.source.index("clearSelection();", start)]

    def test_each_file_is_listed_with_both_dates(self):
        self.assertIn("sync-plan", self.body)
        self.assertIn("fmtRelDate(d.cloudMtime)", self.body)
        self.assertIn("fmtRelDate(d.localMtime)", self.body)

    def test_the_divergence_caveat_is_in_the_confirm_not_just_the_docs(self):
        """Two timestamps cannot distinguish "cloud is newer" from "we both
        changed it", and the person clicking Sync is the one who needs to know."""
        self.assertIn("Two dates cannot tell you whether both sides", self.body)

    def test_the_confirm_says_where_the_other_copy_is(self):
        """It used to promise a `.previous-` file. Backups went in v2.141.0, so
        that promise became untrue - and saying nothing at all would leave a
        bulk overwrite reading as data loss. What is true is that the cloud
        keeps the project it hands down, and that is what has to be on the
        screen where the overwrite is confirmed."""
        self.assertIn("which stays on the cloud afterwards", self.body)
        self.assertIn("No separate copy is kept", self.body)
        self.assertNotIn(".previous-", self.body)

    def test_it_speaks_ekahau_s_vocabulary(self):
        """He already has a mental model from Ekahau's own save prompt: sync
        takes the correct side per file, overwrite forces one direction. Using
        those two words to mean those two things beats teaching him ours."""
        self.assertIn("Sync —", self.body)
        self.assertIn("Sync never overwrites the newer side", self.body)

    def test_blocked_uploads_are_named_in_the_confirm(self):
        self.assertIn("blockedPushes.length", self.body)
        self.assertIn("not sent up", self.body)


class ThereIsStillOneDownloadImplementation(unittest.TestCase):

    def test_bulk_sync_reuses_verify_replace_local(self):
        """Not a second download-and-replace path. The existing one already
        replaces atomically and refuses the unsafe direction."""
        source = CLOUD_JS.read_text(encoding="utf-8")
        start = source.index("for (const d of contentPulls)")
        block = source[start:source.index("for (const d of pairs)", start)]
        self.assertIn("pyApi('verify_replace_local'", block)


if __name__ == "__main__":
    unittest.main()
