"""Rapid clicks build a queue instead of racing each other.

He works through Cloud Manager one row at a time on purpose - "I'm doing all
these individually because it feels safer that way right now" - and found that
clicking the next rename while the last one was still going did not wait for
it. `opEnqueue` was named for a queue and was not one: it created the operation
with `status: 'queued'` and then started an async IIFE on the next line, so
four clicks in four seconds sent four concurrent writes to Ekahau Cloud and
they finished in whatever order the network decided.

The deck was already built for the half that was missing - it renders a
`queued` status, counts "N queued", and has dismiss, cancel and retry. Only the
scheduler was absent, so this adds a FIFO gate rather than a second mechanism.

Everything here drives the real functions sliced out of `cloud.js` in Node.
A queue is a claim about *timing*, and timing is exactly what reading the
source cannot confirm.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
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

// The ops module, from its state down to the end of retry.
const block = slice('const _ops = new Map();', '\nasync function runWithProgress');

// The deck draws; this test is about scheduling, so the drawing is stubbed and
// the assertions read the op records themselves.
const stubs = `
  function e(s) { return String(s == null ? '' : s); }
  function _deckRender() {}
  function _ensureDeckTick() {}
  function _ensureDeckPoll() {}
  function _scheduleOpRefresh() {}
  function toast() {}
  const document = { getElementById: () => null };
`;

const fn = new Function(stubs + block + `
  return { opEnqueue, _opRemove, _ops, _opOrder, _opPending: _opPending,
           opCancelQueued, opCancel, OP_MAX_CONCURRENT, _opCardHtml };
`);
const api = fn();

const sleep = ms => new Promise(r => setTimeout(r, ms));
const log = [];
let concurrentNow = 0;
let concurrentPeak = 0;

function work(name, opts) {
  opts = opts || {};
  return api.opEnqueue({
    title: name,
    type: 'test', pollBackend: false, undoable: false,
    run: async () => {
      concurrentNow++;
      concurrentPeak = Math.max(concurrentPeak, concurrentNow);
      log.push('start:' + name);
      await sleep(opts.ms == null ? 20 : opts.ms);
      concurrentNow--;
      log.push('end:' + name);
      if (opts.fail) throw new Error(name + ' blew up');
      return { ok: true };
    },
  });
}

(async () => {
  const out = {};

  // --- rapid clicks, one after another, no awaiting in between -----------
  const a = work('A'), b = work('B'), c = work('C');
  // Snapshot immediately: at this instant only one may have started.
  out.startedImmediately = log.filter(x => x.startsWith('start:')).length;
  out.pendingRightAfterClicking = api._opPending.length;

  await Promise.allSettled([a.promise, b.promise, c.promise]);
  out.peakConcurrency = concurrentPeak;
  out.order = log.slice();
  out.statuses = ['A', 'B', 'C'].map(n => {
    for (const [, op] of api._ops) if (op.title === n) return op.status;
    return 'missing';
  });

  // --- one failure must not abandon the rest -----------------------------
  log.length = 0;
  const d = work('D'), e2 = work('E', { fail: true }), f = work('F');
  const settled = await Promise.allSettled([d.promise, e2.promise, f.promise]);
  out.afterFailureOrder = log.slice();
  out.settledKinds = settled.map(s => s.status);
  out.statusesAfterFailure = ['D', 'E', 'F'].map(n => {
    for (const [, op] of api._ops) if (op.title === n) return op.status;
    return 'missing';
  });

  // --- a pending item can be pulled out before it runs -------------------
  log.length = 0;
  const g = work('G'), h = work('H'), i = work('I');
  api._opRemove(h.id);            // H has not started; it must never run
  await Promise.allSettled([g.promise, h.promise, i.promise]);
  out.removedOrder = log.slice();
  out.removedEverRan = log.some(x => x === 'start:H');

  // --- what a waiting card actually renders ------------------------------
  const j1 = work('J', { ms: 60 }), j2 = work('K', { ms: 5 }), j3 = work('L', { ms: 5 });
  const cardFor = (h) => {
    for (const [, op] of api._ops) if (op.title === h) return api._opCardHtml(op);
    return '';
  };
  out.cardRunning = cardFor('J');
  out.cardNext = cardFor('K');
  out.cardBehind = cardFor('L');
  await Promise.allSettled([j1.promise, j2.promise, j3.promise]);
  out.cardDone = cardFor('J');

  // --- cancelling work that is already running ---------------------------
  // Nothing forwards the flag to the request and the server has no cancel for
  // a cloud write, so a running upload, replace or delete completes whatever
  // this does. The question is what the card claims afterwards.
  const m = work('M', { ms: 40 });
  let mOp = null;
  for (const [, op] of api._ops) if (op.title === 'M') mOp = op;
  out.runningCardOffersCancel = /opCancel\(/.test(api._opCardHtml(mOp));
  api.opCancel(mOp.id);
  await Promise.allSettled([m.promise]);
  out.statusAfterCancellingWorkThatFinished = mOp.status;
  out.cardAfterCancellingWorkThatFinished = api._opCardHtml(mOp);
  out.cancelledWorkStillRan = log.some(x => x === 'start:M');

  process.stdout.write(JSON.stringify(out));
  /* The sliced block carries the real `_ensureDeckTick`, which starts a
     setInterval to age the cards. Nothing clears it here, so node would stay
     alive on that timer and the test would read as a hang rather than a
     result. Leave deliberately once the answer is out. */
  process.exit(0);
})().catch(err => {
  process.stderr.write(String(err && err.stack || err));
  process.exit(1);
});
"""


_PROBE = {}


def probe():
    """Run the queue once and cache it at module level, so neither class
    depends on which of them unittest happens to run first."""
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
class RapidClicksBuildAQueueTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = probe()

    def test_only_one_operation_runs_at_a_time(self):
        """The whole complaint. Three clicks used to mean three concurrent
        writes to somebody's live projects."""
        self.assertEqual(1, self.out["peakConcurrency"])

    def test_clicking_again_does_not_wait_and_does_not_drop_the_click(self):
        """Clicking during an in-flight operation has to be accepted straight
        away - the point is that he is not blocked - and it has to end up in
        the queue rather than being ignored."""
        self.assertLessEqual(self.out["startedImmediately"], 1)
        self.assertGreaterEqual(self.out["pendingRightAfterClicking"], 1)

    def test_they_run_in_the_order_they_were_clicked(self):
        self.assertEqual(
            ["start:A", "end:A", "start:B", "end:B", "start:C", "end:C"],
            self.out["order"])

    def test_every_item_reports_its_own_result(self):
        """His standing preference across this tool: per-item results, never
        one aggregate "done". A batch that reports a single success is how a
        silent partial failure hides."""
        self.assertEqual(["done", "done", "done"], self.out["statuses"])

    def test_a_failure_marks_that_item_and_the_queue_carries_on(self):
        """One bad item must not abandon the rest - the same lesson as the
        all-or-nothing pass that discarded finished work when a later step
        refused."""
        self.assertEqual(["done", "failed", "done"],
                         self.out["statusesAfterFailure"])
        self.assertIn("start:F", self.out["afterFailureOrder"])
        self.assertEqual(["fulfilled", "rejected", "fulfilled"],
                         self.out["settledKinds"])

    def test_a_failure_does_not_stall_the_slot(self):
        """If the finally-block did not free the slot, everything behind a
        failure would queue forever and the deck would look hung."""
        self.assertEqual(
            ["start:D", "end:D", "start:E", "end:E", "start:F", "end:F"],
            self.out["afterFailureOrder"])

    def test_a_pending_item_can_be_removed_before_it_runs(self):
        """Dismissing something that has not started has to take it out of the
        queue rather than just off the screen, or its turn still arrives and it
        runs after he said not to."""
        self.assertFalse(self.out["removedEverRan"])
        self.assertEqual(
            ["start:G", "end:G", "start:I", "end:I"], self.out["removedOrder"])


class TheWaitingCardSaysWhereItIsTests(unittest.TestCase):
    """The queue has to be legible, not merely correct.

    Four cards all reading "Waiting..." say nothing about which is next. The
    card is rendered through the real `_opCardHtml`, because what he reads is
    the rendered row and asserting on the source would pass while the screen
    said something else.
    """

    @classmethod
    def setUpClass(cls):
        cls.out = probe()

    def test_the_running_one_is_not_labelled_as_waiting(self):
        self.assertIn("status-running", self.out["cardRunning"])
        self.assertNotIn("Waiting", self.out["cardRunning"])

    def test_the_next_one_says_it_is_next(self):
        self.assertIn("status-queued", self.out["cardNext"])
        self.assertIn("next", self.out["cardNext"])

    def test_one_further_back_says_how_many_are_ahead(self):
        self.assertIn("status-queued", self.out["cardBehind"])
        self.assertIn("ahead", self.out["cardBehind"])

    def test_a_waiting_item_offers_a_way_out_before_it_runs(self):
        """He can change his mind about something that has not started."""
        self.assertIn("opCancelQueued", self.out["cardNext"])
        self.assertIn("Remove", self.out["cardNext"])

    def test_a_running_write_does_not_offer_a_cancel_it_cannot_honour(self):
        """Nothing forwards the cancel flag to the request, and Ekahau has no
        cancel for an upload or a delete, so a running cloud write finishes
        whatever the button does.

        A button that stops nothing on an irreversible operation is worse than
        no button: it is the tool saying the delete was called off. Queued work
        is genuinely removable and still offers it - that is the difference.
        """
        self.assertFalse(self.out["runningCardOffersCancel"],
                         "a running write offered Cancel: "
                         + self.out["cardAfterCancellingWorkThatFinished"])

    def test_work_that_finished_is_never_reported_as_cancelled(self):
        """The status was assigned after the run had already returned, so a
        completed upload-verify-delete was labelled Cancelled while the old
        cloud project was gone."""
        self.assertTrue(self.out["cancelledWorkStillRan"],
                        "the fixture did not actually run the work")
        self.assertEqual("done",
                         self.out["statusAfterCancellingWorkThatFinished"])
        self.assertNotIn("Cancelled",
                         self.out["cardAfterCancellingWorkThatFinished"])

    def test_a_finished_item_is_reported_per_item(self):
        self.assertIn("status-done", self.out["cardDone"])


class NothingPromisesACopyThatIsNoLongerKeptTests(unittest.TestCase):
    """The app must not tell him a copy was kept when none is.

    This started life the other way round. Five dialogs said the replaced copy
    sat next to the original; it had moved into a backups folder, and pointing
    someone at the wrong place to find the file they just overwrote is the
    worst sentence in the app to have wrong. Backups were removed entirely in
    v2.141.0, and the same sentences became worse than misplaced - they became
    untrue. A promise of a copy that does not exist is how somebody overwrites
    a file believing they can get it back.

    The replacement for a copy is that a pull takes a project Ekahau is still
    holding, so the cloud *is* the other copy. That is what the dialogs say
    now, and what this holds them to.

    It reads the source because these are sentences rather than behaviour.
    The phrases are the ones that shipped, so a reworded dialog that still
    promises a copy needs adding here - the shape to look for is any sentence
    telling him something is kept.
    """

    #: Every form the old promise took, plus the folder it named.
    WRONG = [
        "alongside it",
        "beside it as a",
        "kept beside it",
        "nothing is pruned",
        ".previous-",
        "backups folder",
        "backups/&lt;site&gt;/",
        "previous copy kept",
        "previous local cop",
    ]

    def test_no_dialog_promises_a_copy_of_the_file_it_replaces(self):
        text = CLOUD_JS.read_text(encoding="utf-8")
        found = [phrase for phrase in self.WRONG if phrase in text]
        self.assertEqual(
            [], found,
            "cloud.js still promises a copy of the replaced file, which the "
            "suite no longer takes: " + ", ".join(found))

    def test_the_dialogs_say_where_the_other_copy_actually_is(self):
        """Saying nothing is not enough. A replace with no stated safety net
        reads as data loss, and the answer - Ekahau still has it - is the
        reason this is safe at all, so it has to be on screen."""
        text = CLOUD_JS.read_text(encoding="utf-8")
        self.assertIn("No second copy is kept - the cloud one is it.", text)
        self.assertIn("which Ekahau still holds", text)


if __name__ == "__main__":
    unittest.main()
