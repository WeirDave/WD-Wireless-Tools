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
eval(slice('function syncPlan(items, dir) {', 'function selectedSyncItems'));

// Only orphan rows consult this; pairs never reach it.
globalThis.isProjectSyncItem = () => true;

const failures = [];
function check(what, cond) { if (!cond) failures.push(what); }
function done() {
  if (failures.length) { console.error(failures.join('\n')); process.exit(1); }
  process.exit(0);
}
function pair(name, staleness) {
  return { kind: 'pair', cloudId: 'c-' + name, cloudName: name,
           localName: name, localPath: '/l/' + name + '.esx',
           staleness: staleness || null, cloudMtime: 200, localMtime: 100 };
}
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
        """The direction that does not exist. It must not fall into the pull
        bucket, and must not be quietly dropped either."""
        self.run_block("""
          var plan = syncPlan([pair('a','local_newer')], 'to-local');
          check('not pulled down over the newer local file',
                plan.contentPulls.length === 0);
          check('not silently renamed instead', plan.pairs.length === 0);
          check('reported as blocked so the confirm can name it',
                plan.blockedPushes.length === 1);
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
          check('one is blocked: ' + names(plan.blockedPushes),
                names(plan.blockedPushes) === 'up1');
          check('one is a plain rename: ' + names(plan.pairs),
                names(plan.pairs) === 'same');
          check('the blocked one is not counted as work: ' + plan.total,
                plan.total === 3);
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

    def test_the_backup_is_promised_where_the_overwrite_is_confirmed(self):
        self.assertIn(".previous-", self.body)

    def test_blocked_uploads_are_named_in_the_confirm(self):
        self.assertIn("blockedPushes.length", self.body)
        self.assertIn("not sent up", self.body)


class ThereIsStillOneDownloadImplementation(unittest.TestCase):

    def test_bulk_sync_reuses_verify_replace_local(self):
        """Not a second download-and-replace path. The existing one already
        backs up, replaces atomically, and refuses the unsafe direction."""
        source = CLOUD_JS.read_text(encoding="utf-8")
        start = source.index("for (const d of contentPulls)")
        block = source[start:source.index("for (const d of pairs)", start)]
        self.assertIn("pyApi('verify_replace_local'", block)


if __name__ == "__main__":
    unittest.main()
