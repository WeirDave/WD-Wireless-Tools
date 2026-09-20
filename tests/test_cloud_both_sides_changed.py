""""Both of you changed it" is a state the tool can reach now.

Two timestamps cannot separate "they changed it" from "we both changed it".
A cloud copy dated later than the local one says the cloud moved; it says
nothing about whether the local one moved too, because there is nothing to
compare it against. So `syncEverythingPlan` sorted every pair into
`cloud_newer`, `local_newer` or in-sync, and a pair where both sides had been
edited was reported as an ordinary one-way difference and copied over.

`tools/sync_state.py` records the third number - what the pair looked like the
last time this machine made the two sides identical - and four states fall out
of two comparisons.

**Nothing resolves a divergence, and that is the feature.** The tool can now
recognise the case it was silently overwriting; the only correct behaviour is
to take it out of the run and say so. Two of these tests exist specifically to
fail if anything ever starts picking a winner.

Every project, path and address here is invented, and no test writes outside
its own temporary directory.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tools import sync_state as ss

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 120


class TheRecordIsWrittenAndReadTests(unittest.TestCase):

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, True)
        self.f = self.dir / "sync_state.json"

    def test_a_pair_is_recorded_and_comes_back(self):
        ss.record("c-1", r"D:\E\SITE1.esx", 1000, 900, "pull", _path=self.f)
        got = ss.load(_path=self.f)
        self.assertIn("c-1", got)
        self.assertEqual(1000, got["c-1"]["cloudMtime"])
        self.assertEqual(900, got["c-1"]["localMtime"])
        self.assertEqual("pull", got["c-1"]["direction"])

    def test_a_missing_file_is_no_record_rather_than_an_error(self):
        self.assertEqual({}, ss.load(_path=self.dir / "never.json"))

    def test_a_corrupt_file_degrades_to_no_record(self):
        """The fallback has to be "I don't know", which is where the tool
        started. Raising here would break the listing for every project."""
        self.f.write_text("{ this is not json", encoding="utf-8")
        self.assertEqual({}, ss.load(_path=self.f))

    def test_a_record_with_no_id_or_path_is_not_written(self):
        ss.record("", "somewhere", 1, 1, _path=self.f)
        ss.record("c-1", "", 1, 1, _path=self.f)
        self.assertEqual({}, ss.load(_path=self.f))

    def test_a_second_sync_replaces_the_first(self):
        ss.record("c-1", "p", 1000, 900, _path=self.f)
        ss.record("c-1", "p", 2000, 1900, _path=self.f)
        self.assertEqual(2000, ss.load(_path=self.f)["c-1"]["cloudMtime"])

    def test_forgetting_removes_one_and_leaves_the_rest(self):
        ss.record("c-1", "p1", 1, 1, _path=self.f)
        ss.record("c-2", "p2", 1, 1, _path=self.f)
        ss.forget("c-1", _path=self.f)
        self.assertEqual(["c-2"], sorted(ss.load(_path=self.f)))

    def test_pruning_drops_projects_that_are_gone(self):
        """Otherwise the file grows for the life of the install, and a
        recycled id reads against a record for something else."""
        ss.record("c-1", "p1", 1, 1, _path=self.f)
        ss.record("c-2", "p2", 1, 1, _path=self.f)
        ss.record("c-3", "p3", 1, 1, _path=self.f)
        gone = ss.prune(["c-2"], _path=self.f)
        self.assertEqual(2, gone)
        self.assertEqual(["c-2"], sorted(ss.load(_path=self.f)))

    def test_the_file_is_valid_json_with_a_version(self):
        """A version, because this file will outlive its first shape and
        something has to be able to tell which one it is reading."""
        ss.record("c-1", "p", 1, 1, _path=self.f)
        data = json.loads(self.f.read_text(encoding="utf-8"))
        self.assertEqual(["pairs", "version"], sorted(data))
        self.assertEqual(1, data["version"])


class TheFourStatesTests(unittest.TestCase):
    """Two comparisons against the recorded pair, and what each one means."""

    REC = {"localPath": r"D:\E\SITE1.esx", "cloudMtime": 1000,
           "localMtime": 1000, "syncedAt": 1000, "direction": "pull"}

    def v(self, cloud_now, local_now, path=r"D:\E\SITE1.esx", rec=None):
        return ss.classify(self.REC if rec is None else rec,
                           cloud_now, local_now, path)

    def test_neither_side_moved_is_in_sync(self):
        self.assertEqual(ss.IN_SYNC, self.v(1000, 1000))

    def test_only_the_cloud_moved(self):
        self.assertEqual(ss.CLOUD_CHANGED, self.v(5000, 1000))

    def test_only_the_local_file_moved(self):
        self.assertEqual(ss.LOCAL_CHANGED, self.v(1000, 5000))

    def test_both_moved_is_the_state_two_timestamps_could_not_express(self):
        """The whole point. Note that the cloud is also *newer* here, so the
        old comparison called this `cloud_newer` and pulled over the local
        work without mentioning it."""
        self.assertEqual(ss.BOTH_CHANGED, self.v(5000, 4000))

    def test_both_moved_is_found_whichever_side_is_newer(self):
        self.assertEqual(ss.BOTH_CHANGED, self.v(4000, 5000))

    def test_a_pair_never_synced_here_says_unknown(self):
        self.assertEqual(ss.UNKNOWN, ss.classify(None, 1, 2, "p"))

    def test_a_local_file_renamed_since_the_sync_says_unknown(self):
        """The record describes a file that is no longer at that path. An
        unknown answer is safe; a confident one against the wrong file is
        how the wrong project gets overwritten."""
        self.assertEqual(ss.UNKNOWN, self.v(1000, 1000, path=r"D:\E\Other.esx"))

    def test_the_path_comparison_ignores_slash_direction_and_case(self):
        """It is one machine's own record of its own files - a Windows path
        written two ways is the same file, and refusing there would throw
        away a good record for nothing."""
        self.assertEqual(ss.IN_SYNC, self.v(1000, 1000, path="d:/e/site1.esx"))

    def test_a_missing_timestamp_on_either_side_says_unknown(self):
        self.assertEqual(ss.UNKNOWN, self.v(0, 1000))
        self.assertEqual(ss.UNKNOWN, self.v(1000, 0))
        self.assertEqual(ss.UNKNOWN, self.v(1000, 1000,
                                            rec={**self.REC, "cloudMtime": 0}))

    def test_a_second_of_drift_is_not_a_change(self):
        """Filesystems and APIs disagree about a second or two, and a pair
        that nobody touched must not read as diverged on rounding."""
        self.assertEqual(ss.IN_SYNC, self.v(1001, 999))

    def test_a_side_restored_to_an_older_copy_counts_as_changed(self):
        """Moving backwards is a change. Treating it as unchanged would let
        the other side silently overwrite a deliberate restore."""
        self.assertEqual(ss.CLOUD_CHANGED, self.v(500, 1000))
        self.assertEqual(ss.BOTH_CHANGED, self.v(500, 400))


class ThePlanRefusesToResolveItTests(unittest.TestCase):
    """The payoff, driven through the real `syncEverythingPlan`.

    A pair whose two sides have both moved must leave the run entirely - not
    be sorted into a direction, and not be quietly counted as in-sync either,
    which would be the same silence wearing a different label.
    """

    PROGRAM = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
function slice(from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return src.slice(a, b);
}
const sandbox = { console, JSON, Math, Set, Map, RegExp };
sandbox.data = JSON.parse(process.argv[2]);
sandbox.iOwn = () => true;
sandbox.selectedSyncItems = () => [];
vm.createContext(sandbox);
vm.runInContext(
  slice('const PULLABLE_MATCH_TYPES', 'function compareResultFor(')
  + slice('function syncEverythingPlan(', '\nfunction _syncRowsHtml(')
  + '\nglobalThis.__plan = syncEverythingPlan();', sandbox);
const p = sandbox.__plan;
console.log(JSON.stringify({
  down: p.down.map(r => r.cloudName),
  up: p.up.map(r => r.cloudName),
  inSync: p.inSync.map(r => r.cloudName),
  diverged: (p.diverged || []).map(r => r.cloudName),
}));
"""

    @staticmethod
    def _pair(name, cid, staleness, divergence):
        return {
            "cloud": {"id": cid, "name": name, "mtime": 5000, "owner": "me@example.invalid"},
            "local": {"path": "D:\\E\\" + name + ".esx", "name": name, "mtime": 4000},
            "matchType": "id", "staleness": staleness,
            "divergence": divergence, "namesDiffer": False,
        }

    def _plan(self, pairs):
        node = shutil.which("node")
        if not node:  # pragma: no cover
            raise unittest.SkipTest("node is not available")
        data = {"currentUser": "me@example.invalid", "matched": pairs,
                "cloudOnly": [], "localOnly": [],
                "orphans": {"cloudOnly": []}}
        r = subprocess.run([node, "-e", self.PROGRAM, str(CLOUD_JS),
                            json.dumps(data)],
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError("plan failed:\n" + (r.stderr or "")[-2500:])
        return json.loads(r.stdout.strip().splitlines()[-1])

    def test_an_ordinary_cloud_newer_pair_still_runs(self):
        got = self._plan([self._pair("Alpha", "c1", "cloud_newer", "cloud_changed")])
        self.assertEqual(["Alpha"], got["down"])
        self.assertEqual([], got["diverged"])

    def test_a_pair_that_moved_on_both_sides_leaves_the_run(self):
        """It looks exactly like `cloud_newer` to the old comparison - the
        cloud date is the later one - which is why it was being pulled over
        the local work without a word."""
        got = self._plan([self._pair("Bravo", "c2", "cloud_newer", "both_changed")])
        self.assertEqual([], got["down"], "it was still queued for download")
        self.assertEqual([], got["up"])
        self.assertEqual(["Bravo"], got["diverged"])

    def test_it_is_not_counted_as_already_matching_either(self):
        """Dropping it into `inSync` would be the same silence with a nicer
        label - he would be told the pair needs nothing."""
        got = self._plan([self._pair("Charlie", "c3", "local_newer", "both_changed")])
        self.assertEqual([], got["inSync"])
        self.assertEqual(["Charlie"], got["diverged"])

    def test_a_pair_this_machine_has_never_synced_behaves_as_before(self):
        """Most pairs on the first run. `unknown` must change nothing, or the
        feature breaks the tool for everyone until they have synced once."""
        got = self._plan([self._pair("Delta", "c4", "cloud_newer", "unknown")])
        self.assertEqual(["Delta"], got["down"])
        self.assertEqual([], got["diverged"])

    def test_a_mixed_account_splits_correctly(self):
        got = self._plan([
            self._pair("Alpha", "c1", "cloud_newer", "cloud_changed"),
            self._pair("Bravo", "c2", "cloud_newer", "both_changed"),
            self._pair("Delta", "c4", "cloud_newer", "unknown"),
        ])
        self.assertEqual(["Alpha", "Delta"], sorted(got["down"]))
        self.assertEqual(["Bravo"], got["diverged"])


class TheDialogSaysWhatHappenedTests(unittest.TestCase):
    """A pair silently removed from the run is the original defect wearing a
    different hat, so the confirm has to name them and say why.

    Driven: the real body-building block is executed against a plan holding
    one diverged pair, and the sentence it produces is read back.
    """

    PROGRAM = r"""
const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync(process.argv[1], 'utf8');
function slice(from, to) {
  const a = src.indexOf(from), b = src.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return src.slice(a, b);
}
const sandbox = { console, JSON, Math, Set, Map, RegExp };
sandbox.e = (x) => String(x == null ? '' : x);
sandbox.plan = JSON.parse(process.argv[2]);
sandbox.body = '';
vm.createContext(sandbox);
// The stretch of `syncEverything` that turns a plan into the confirm body.
vm.runInContext(
  slice("  if (plan.upBlocked.length || plan.downBlocked.length) {",
        "  /* `showConfirmModal` empties the body"), sandbox);
console.log(JSON.stringify({ body: sandbox.body }));
"""

    def _body(self, plan):
        node = shutil.which("node")
        if not node:  # pragma: no cover
            raise unittest.SkipTest("node is not available")
        base = {"down": [], "up": [], "upBlocked": [], "downBlocked": [],
                "fresh": [], "inSync": [], "diverged": []}
        base.update(plan)
        r = subprocess.run([node, "-e", self.PROGRAM, str(CLOUD_JS),
                            json.dumps(base)],
                           capture_output=True, text=True, encoding="utf-8",
                           timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError("body failed:\n" + (r.stderr or "")[-2500:])
        return json.loads(r.stdout.strip().splitlines()[-1])["body"]

    def test_a_diverged_pair_is_named_in_the_confirm(self):
        body = self._body({"diverged": [
            {"cloudName": "Bravo Survey", "localName": "Bravo Survey"}]})
        self.assertIn("Bravo Survey", body,
                      "a pair was dropped from the run without being named")
        self.assertIn("both", body.lower())

    def test_it_says_why_rather_than_only_that_it_was_skipped(self):
        body = self._body({"diverged": [
            {"cloudName": "Bravo Survey", "localName": "Bravo Survey"}]})
        self.assertIn("discard", body.lower(),
                      "it does not say what copying would cost")
        self.assertIn("Check what differs", body,
                      "it names no way of finding out what changed")

    def test_nothing_is_said_when_no_pair_diverged(self):
        """A warning that fires on the ordinary case is one he learns to
        scroll past."""
        body = self._body({"inSync": [{"cloudName": "Alpha"}]})
        self.assertNotIn("both", body.lower())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
