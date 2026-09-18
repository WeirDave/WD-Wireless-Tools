"""Sending a newer local file up over the cloud project it is paired with.

`replace_cloud_project` shipped in v2.104.6 with its server route and nothing
calling it, so for three releases the row showed a greyed "Local → Cloud" that
said the direction was not built while the code sat in the file. This covers
the control that finally reaches it.

Two things are asserted, because two things can go wrong and they are not the
same kind of wrong.

**Who may push.** Narrower than who may pull, deliberately. A pull keeps the
file it replaced in `backups/<site>/`; a push deletes the old cloud project and
a cloud delete does not come back. So a pull is offered on a bare name match
and a push is not - it wants Ekahau's own id, or a pairing he made himself.
Getting this wrong destroys a project that was never the counterpart.

**What it says when it half-works.** Upload succeeded, delete of the old one
did not, and there are now two projects with the same name. That is the exact
situation he has been bitten by twice and the one he checks for first, so it
has to be said in words - including which of the two is the good copy - rather
than surfacing as a bare failure.
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

// A row's controls are built from the shared icon helpers, and those sit
// above the badges. Slicing from the badges alone compiles and then throws
// `ic is not defined` on the first render - so the slice starts higher
// rather than the helper being stubbed, because a stub would test the stub.
const block = slice('const ICONS = {', '\nfunction siteDigest(')
            + slice('const MATCH_BADGE_SPEC = {', '\nfunction gutCell(r)');

const WD = { esc: s => String(s == null ? '' : s),
             escAttr: s => String(s == null ? '' : s),
             escJsStr: s => String(s == null ? '' : s) };
function e(s) { return WD.esc(s); }
function a(s) { return WD.escAttr(s); }
function j(s) { return WD.escJsStr(s); }
function pj(s) { return j(String(s == null ? '' : s).replace(/\\/g, '/')); }
let currentTab = 'projects';

// Captured instead of performed: the queue and the server are other tests.
let enqueued = null;
const toasts = [];
let apiResult = null;
function opEnqueue(spec) { enqueued = spec; return { id: 'op1', promise: Promise.resolve() }; }
function toast(msg, kind) { toasts.push({ msg: String(msg), kind }); }
async function pyApi() { return apiResult; }
function _clearStaleness() {}
function _scheduleOpRefresh() {}

const fn = new Function('WD','e','a','j','pj','currentTab','opEnqueue','toast','pyApi','_clearStaleness','_scheduleOpRefresh',
  block + '\nreturn { stalenessBadgeHtml, canPushToCloud, pushLocalOverCloud };');
const api = fn(WD,e,a,j,pj,currentTab,opEnqueue,toast,pyApi,_clearStaleness,_scheduleOpRefresh);

const row = (over) => Object.assign({
  kind: 'projects',
  matchType: 'id',
  staleness: 'local_newer',
  differenceKind: 'content',
  cloud: { id: 'c1', name: 'SITE1 Survey', mtime: 100 },
  local: { path: 'C:/x/a.esx', name: 'SITE1 Survey', mtime: 200 },
}, over || {});

const out = { badge: {}, gate: {} };
for (const mt of ['id', 'manual', 'exact', 'code', 'fuzzy']) {
  out.badge[mt] = api.stalenessBadgeHtml(row({ matchType: mt }));
  out.gate[mt] = api.canPushToCloud(row({ matchType: mt }));
}
out.gateSite = api.canPushToCloud(row({ kind: 'sites', local: { path: 'C:/x/site', name: 's' } }));

(async () => {
  // success
  apiResult = { ok: true, newId: 'n1', oldId: 'c1', name: 'SITE1 Survey', deletedOld: true };
  api.pushLocalOverCloud('c1', 'C:/x/a.esx', 'SITE1 Survey', 'SITE1 Survey');
  toasts.length = 0;
  out.okResult = await enqueued.run('op1');
  out.okToasts = toasts.map(t => t);

  // upload failed - nothing deleted
  apiResult = { error: 'Upload failed', step: 'upload', deletedOld: false,
                note: 'Nothing was deleted - the old cloud project is untouched.' };
  api.pushLocalOverCloud('c1', 'C:/x/a.esx', 'SITE1 Survey', 'SITE1 Survey');
  toasts.length = 0;
  try { await enqueued.run('op1'); out.uploadFailThrew = false; }
  catch (err) { out.uploadFailThrew = true; out.uploadFailMsg = err.message; }
  out.uploadFailToasts = toasts.map(t => t);

  // the dangerous one: uploaded, old not removed, two copies now
  apiResult = { ok: false, step: 'delete', deletedOld: false, newId: 'n1', oldId: 'c1',
                error: 'The new copy uploaded correctly, but the old one could not be removed: 500',
                note: 'There are now two projects named SITE1 Survey. The newer one is the good copy; delete the other when you can.' };
  api.pushLocalOverCloud('c1', 'C:/x/a.esx', 'SITE1 Survey', 'SITE1 Survey');
  toasts.length = 0;
  try { await enqueued.run('op1'); out.deleteFailThrew = false; }
  catch (err) { out.deleteFailThrew = true; out.deleteFailMsg = err.message; }
  out.deleteFailToasts = toasts.map(t => t);

  out.enqueueSpec = { title: enqueued.title, sub: enqueued.sub, type: enqueued.type,
                      pollBackend: enqueued.pollBackend, undoable: enqueued.undoable };

  process.stdout.write(JSON.stringify(out));
  process.exit(0);
})().catch(err => { process.stderr.write(String(err && err.stack || err)); process.exit(1); });
"""


_PROBE = {}


def probe():
    """Run the page's own code once and cache it.

    Both classes below read the same run. Hanging the result off one of them
    and reaching for it from the other is a dependency on class ordering, and
    unittest runs them alphabetically - which put the reader before the writer
    and failed on an attribute that did not exist yet.
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
class OnlyAProvenPairMayReplaceTheCloudCopyTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = probe()

    def test_an_ekahau_id_match_may_push(self):
        """The stamp inside both files. This is the normal case."""
        self.assertTrue(self.out["gate"]["id"])
        self.assertIn("pushLocalOverCloud(", self.out["badge"]["id"])

    def test_a_pairing_he_made_himself_may_push(self):
        self.assertTrue(self.out["gate"]["manual"])
        self.assertIn("pushLocalOverCloud(", self.out["badge"]["manual"])

    def test_a_name_only_match_may_push_but_is_asked_first(self):
        """This asserted the opposite and that assertion was the bug.

        Excluding a name match made the control unusable for the pair he
        actually has: a project built locally and uploaded carries Ekahau's id
        only in the *cloud* copy, so "local is newer, no shared id" is the
        normal state of work in progress. It is allowed now and confirms first,
        naming the cloud project it will delete - friction rather than a wall.
        `test_cloud_push_is_reachable.py` drives that path.
        """
        self.assertTrue(self.out["gate"]["exact"])
        self.assertIn("pushLocalOverCloud(", self.out["badge"]["exact"])

    def test_a_guessed_match_may_not(self):
        for mt in ("code", "fuzzy"):
            self.assertFalse(self.out["gate"][mt], mt)
            self.assertNotIn("pushLocalOverCloud(", self.out["badge"][mt], mt)

    def test_a_site_row_may_not(self):
        """A site's local side is a folder, not an .esx."""
        self.assertFalse(self.out["gateSite"])

    def test_a_guessed_pair_is_told_how_to_make_itself_proven(self):
        """Shown and unavailable with a route out, never absent - the original
        complaint about this row was a control that did nothing.

        Only a *guessed* pairing lands here now: a shared site code, or similar
        wording. The two names are not the same, so there is nothing for him to
        confirm against and Link is the honest answer."""
        html = self.out["badge"]["fuzzy"]
        self.assertIn('aria-disabled="true"', html)
        self.assertIn("Link", html)
        self.assertIn("cannot be undone", html)

    def test_the_control_states_the_order_before_it_runs(self):
        """No confirm dialog for a single row, so the button itself has to say
        what it will do. The order is the safety."""
        html = self.out["badge"]["id"]
        self.assertIn("only then removes the old", html)
        self.assertIn("If the upload fails nothing is deleted", html)


@unittest.skipIf(shutil.which("node") is None, "node is not installed")
class EveryOutcomeIsReportedAsItselfTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.out = probe()

    def test_it_goes_through_the_queue(self):
        """Serialised with everything else rather than firing on its own."""
        spec = self.out["enqueueSpec"]
        self.assertEqual("push", spec["type"])
        self.assertTrue(spec["pollBackend"], "it reports progress while running")
        self.assertFalse(spec["undoable"], "a deleted cloud project cannot be undone")

    def test_success_says_the_old_one_was_removed(self):
        joined = " ".join(t["msg"] for t in self.out["okToasts"])
        self.assertIn("replaced", joined)
        self.assertIn("old one was removed", joined)

    def test_a_failed_upload_says_nothing_was_deleted(self):
        """The reassurance that matters on a failure: the cloud is untouched."""
        self.assertTrue(self.out["uploadFailThrew"])
        self.assertIn("Nothing was deleted", self.out["uploadFailMsg"])

    def test_a_failed_delete_says_there_are_two_and_which_is_good(self):
        """The duplicate case. He has hit this twice from other causes and
        checks for it first, so it is stated rather than implied - as a toast
        as well as on the card, because a failed card can be scrolled past."""
        self.assertTrue(self.out["deleteFailThrew"])
        msg = self.out["deleteFailMsg"]
        self.assertIn("two projects named", msg)
        self.assertIn("newer one is the good copy", msg)
        joined = " ".join(t["msg"] for t in self.out["deleteFailToasts"])
        self.assertIn("two projects named", joined)

    def test_the_note_is_never_dropped_on_the_floor(self):
        """`note` is where the backend says what state the cloud is actually
        in. Reporting only `error` would turn the most important sentence into
        a generic failure."""
        for key in ("uploadFailMsg", "deleteFailMsg"):
            self.assertGreater(len(self.out[key]), 60, key)


if __name__ == "__main__":
    unittest.main()
