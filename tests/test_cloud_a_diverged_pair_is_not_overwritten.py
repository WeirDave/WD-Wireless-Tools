"""A pair where BOTH sides were edited is not overwritten by a single click.

Two dates cannot tell "the cloud moved" from "we both moved". The cloud copy
edited at 09:00 and the local file at 10:00 reads as a plain "local is newer",
and `replace_cloud_project` then deletes the 09:00 work; the mirror image reads
as "cloud is newer" and `verify_replace_local` overwrites the 10:00 work.

The record of what the pair last looked like (`tools/sync_state.py`) *can*
tell, and `classify` had one consumer: the whole-account Sync planner, which
takes a diverged pair out of its run. The single-row Pull and Push, and every
bulk path that reaches them, asked the server only about dates. The page's
verdict is a snapshot from when the list was drawn, so the server reads the
record itself at the moment of the write.

It is friction, not a wall (CLAUDE.md, "Unrecoverable earns friction"): a pull
is lifted by the contents proving the cloud copy holds nothing less, and a push
by a confirm that names what is lost. A pair this machine holds no record of is
`unknown` and is not refused - the guard must not fire on the ordinary case.

Every project, path and address here is invented, nothing contacts Ekahau and
every file lives in a temporary directory that is removed afterwards.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import cloud_manager as cm  # noqa: E402
from tools import sync_state  # noqa: E402

CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 120

#: The last time the two were the same, then each side's later edit.
SYNCED = "2026-09-01T08:00:00.000Z"
LOCAL_EDIT = "2026-09-02T10:00:00.000Z"
CLOUD_EDIT = "2026-09-03T09:00:00.000Z"


def _ts(iso):
    from datetime import datetime
    return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def _esx(path: Path, modified_iso: str, aps=(1,), project_id="proj-1"):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project.json", json.dumps({"project": {
            "id": project_id, "name": path.stem, "title": path.stem,
            "history": {"modifiedAt": modified_iso}}}))
        z.writestr("accessPoints.json", json.dumps({"accessPoints": [
            {"id": "ap-%d" % i, "name": "AP-%03d" % i} for i in aps]}))
        z.writestr("floorPlans.json", json.dumps({"floorPlans": []}))


class _Resp:
    def __init__(self, code, payload=None):
        self.status_code = code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _OwnStateMixin:
    """A sync-point store of its own, so no test reads or writes his."""

    def _own_state(self):
        d = Path(tempfile.mkdtemp(prefix="wd-diverged-state-"))
        self.addCleanup(shutil.rmtree, d, True)
        real = sync_state.STATE_FILE
        sync_state.STATE_FILE = d / "sync_state.json"
        self.addCleanup(lambda: setattr(sync_state, "STATE_FILE", real))
        cm._ESX_META_CACHE.clear()
        self.addCleanup(cm._ESX_META_CACHE.clear)

    def _record_sync_point(self, cloud_id, path):
        sync_state.record(cloud_id, str(path), _ts(SYNCED), _ts(SYNCED),
                          direction="download",
                          local_size=Path(path).stat().st_size)


class ThePullKeepsWorkMadeHereTests(_OwnStateMixin, unittest.TestCase):

    def setUp(self):
        self._own_state()
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-diverged-pull-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.local = self.tmp / "Example Survey.esx"

    def _cloud_bytes(self, aps):
        p = self.tmp / "_cloud.esx"
        _esx(p, CLOUD_EDIT, aps=aps)
        data = p.read_bytes()
        p.unlink()
        return data

    def _pull(self, cloud_bytes):
        mgr = cm.CloudManager.__new__(cm.CloudManager)
        mgr.config = {"output_dir": str(self.tmp)}
        mgr._ensure = lambda: True

        class Api:
            def get(self, url):
                return _Resp(200, {"name": "Example Survey",
                                   "modifiedAt": CLOUD_EDIT})

            def download_project(self, project_id, progress_cb=None):
                return {"esx": cloud_bytes}
        mgr.api = Api()
        return mgr.verify_replace_local("cloud-1", str(self.local))

    def test_both_sides_edited_is_refused_and_the_local_file_is_untouched(self):
        """Local edited on the 2nd (an extra AP), cloud edited on the 3rd (a
        different one). The cloud date is later, so the date test alone sees
        an ordinary "cloud is newer" and overwrites the local work."""
        _esx(self.local, SYNCED, aps=(1,))
        self._record_sync_point("cloud-1", self.local)
        _esx(self.local, LOCAL_EDIT, aps=(1, 2))
        cm._ESX_META_CACHE.clear()
        before = self.local.read_bytes()

        res = self._pull(self._cloud_bytes(aps=(1, 3)))

        self.assertEqual("diverged", res.get("error"), res)
        self.assertEqual(before, self.local.read_bytes(),
                         "the local file was overwritten on a diverged pair")
        self.assertEqual([], [p for p in self.tmp.iterdir()
                              if p != self.local],
                         "a refused pull left a file behind")

    def test_the_refusal_names_what_it_did_and_did_not_do(self):
        _esx(self.local, SYNCED, aps=(1,))
        self._record_sync_point("cloud-1", self.local)
        _esx(self.local, LOCAL_EDIT, aps=(1, 2))
        cm._ESX_META_CACHE.clear()
        res = self._pull(self._cloud_bytes(aps=(1, 3)))
        self.assertIn("Nothing was changed", res.get("message", ""))

    def test_only_the_cloud_moved_is_still_an_ordinary_pull(self):
        """The guard must not fire on the case the Pull button exists for."""
        _esx(self.local, SYNCED, aps=(1,))
        self._record_sync_point("cloud-1", self.local)
        cm._ESX_META_CACHE.clear()
        cloud = self._cloud_bytes(aps=(1, 3))

        res = self._pull(cloud)

        self.assertTrue(res.get("ok"), res)
        self.assertEqual(cloud, self.local.read_bytes())

    def test_a_pair_with_no_record_is_not_refused_by_the_record(self):
        """`unknown` means fall back to the dates - the behaviour before the
        record existed - not a new refusal for every pair on a fresh
        install."""
        _esx(self.local, SYNCED, aps=(1,))
        cm._ESX_META_CACHE.clear()
        cloud = self._cloud_bytes(aps=(1, 3))

        res = self._pull(cloud)

        self.assertTrue(res.get("ok"), res)

    def test_a_diverged_pair_whose_contents_match_is_not_held_up(self):
        """Lifted by what he can check: the same design on both sides loses
        nothing, so nothing is refused. Without this the guard would send him
        to delete the file and download it again, which is this pull with the
        guard removed by hand."""
        _esx(self.local, SYNCED, aps=(1,))
        self._record_sync_point("cloud-1", self.local)
        _esx(self.local, LOCAL_EDIT, aps=(1, 2))
        cm._ESX_META_CACHE.clear()
        same_design = self.tmp / "_same.esx"
        _esx(same_design, CLOUD_EDIT, aps=(1, 2))
        cloud = same_design.read_bytes()
        same_design.unlink()

        res = self._pull(cloud)

        self.assertTrue(res.get("ok"), res)


class _StubApi:
    def __init__(self, cloud_modified):
        self.projects = [{"id": "old-1", "name": "Alpha Survey",
                          "history": {"modifiedAt": cloud_modified}}]
        self.calls = []

    def get_projects(self):
        return list(self.projects)

    def get_dataset_listing(self):
        return [{"id": "old-1", "siteId": "site-9"}]

    def delete_project(self, pid):
        self.calls.append("delete")
        return {"ok": True}


class _Manager(cm.CloudManager):
    def __init__(self, api, out_dir):
        self.api = api
        self.config = {"output_dir": str(out_dir)}
        self.uploads = 0

    def _ensure(self):
        return True

    def _ownership(self, ids):
        return {i: (cm.OWNED, "me@example.com") for i in ids}

    def upload_project(self, esx_path, site_id=None, progress_cb=None):
        self.uploads += 1
        return {"error": "stopped here: the guard under test is before this"}


class ThePushKeepsWorkMadeInTheCloudTests(_OwnStateMixin, unittest.TestCase):

    def setUp(self):
        self._own_state()
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-diverged-push-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.local = self.tmp / "Alpha Survey.esx"
        _esx(self.local, SYNCED)
        self._record_sync_point("old-1", self.local)

    def _push(self, local_edit, cloud_edit, **kw):
        _esx(self.local, local_edit, aps=(1, 2))
        cm._ESX_META_CACHE.clear()
        api = _StubApi(cloud_edit)
        mgr = _Manager(api, self.tmp)
        return mgr, api, mgr.replace_cloud_project(str(self.local), "old-1",
                                                   **kw)

    def test_cloud_edited_before_local_is_refused_before_anything_is_sent(self):
        """The case the date test cannot see: cloud edited on the 2nd, local
        on the 3rd. "Local is newer", so it used to upload and then delete the
        cloud project - and the second-of-the-month work with it."""
        mgr, api, res = self._push(local_edit=CLOUD_EDIT, cloud_edit=LOCAL_EDIT)
        self.assertEqual("diverged", res.get("error"), res)
        self.assertEqual("both_changed", res.get("divergence"))
        self.assertFalse(res.get("deletedOld"))
        self.assertEqual(0, mgr.uploads, "an upload was sent on a refusal")
        self.assertEqual([], api.calls, "something was deleted on a refusal")

    def test_the_confirmed_overwrite_gets_past_the_guard(self):
        """Friction, not a wall: the route the newer-cloud confirm already
        uses lifts this one, and it reaches the upload."""
        mgr, api, res = self._push(local_edit=CLOUD_EDIT,
                                   cloud_edit=LOCAL_EDIT,
                                   overwrite_newer=True)
        self.assertEqual("upload", res.get("step"), res)
        self.assertEqual(1, mgr.uploads)

    def test_only_the_local_file_edited_is_an_ordinary_push(self):
        mgr, api, res = self._push(local_edit=LOCAL_EDIT, cloud_edit=SYNCED)
        self.assertEqual("upload", res.get("step"), res)
        self.assertEqual(1, mgr.uploads)

    def test_a_pair_with_no_record_is_not_refused(self):
        sync_state.forget("old-1")
        mgr, api, res = self._push(local_edit=CLOUD_EDIT, cloud_edit=LOCAL_EDIT)
        self.assertEqual("upload", res.get("step"), res)
        self.assertEqual(1, mgr.uploads)


NODE_SCRIPT = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[2], 'utf8');
const a0 = source.indexOf('function _enqueuePushLocalOverCloud(');
const b0 = source.indexOf('async function replaceNewerCloudWithLocal(', a0);
if (a0 < 0 || b0 < 0) throw new Error('the push function moved');
const block = source.slice(a0, b0);

let enqueued = null, asked = 0, answer = true;
const calls = [];
let replies = [];
const toasts = [];
function e(s) { return String(s == null ? '' : s); }
function opEnqueue(spec) { enqueued = spec; return { id: 'op1', promise: Promise.resolve() }; }
async function pyApi(name, ...args) { calls.push([name, ...args]); return replies.shift(); }
async function showConfirmModal() { asked++; return answer; }
function toast(m, k) { toasts.push(m); }
function _setRowBusy() {}
function _clearStaleness() {}
function _scheduleOpRefresh() {}
function settlePair() { return Promise.resolve(); }

const api = new Function('opEnqueue','pyApi','showConfirmModal','toast','e',
  '_setRowBusy','_clearStaleness','_scheduleOpRefresh','settlePair',
  block + '\nreturn _enqueuePushLocalOverCloud;')(
  opEnqueue, pyApi, showConfirmModal, toast, e,
  _setRowBusy, _clearStaleness, _scheduleOpRefresh, settlePair);

const DIV = { error: 'diverged', divergence: 'both_changed',
              message: 'Both have changed.', deletedOld: false };
const out = {};
(async () => {
  // Confirmed: asked once, then sent again with the overwrite flag.
  replies = [DIV, { ok: true, newId: 'n1', oldId: 'c1', deletedOld: true }];
  calls.length = 0; asked = 0; answer = true;
  api('c1', 'C:/x/a.esx', 'A', 'A');
  await enqueued.run('op1');
  out.yes = { asked, flags: calls.map(c => c[4]), n: calls.length };

  // Declined: asked once, never sent again, and it reads as a stop.
  replies = [DIV]; calls.length = 0; asked = 0; answer = false;
  api('c1', 'C:/x/a.esx', 'A', 'A');
  try { await enqueued.run('op1'); out.no = { threw: false }; }
  catch (err) { out.no = { threw: true, msg: err.message, asked, n: calls.length }; }

  // Not diverged: never asked.
  replies = [{ ok: true, newId: 'n1', oldId: 'c1', deletedOld: true }];
  calls.length = 0; asked = 0; answer = true;
  api('c1', 'C:/x/a.esx', 'A', 'A');
  await enqueued.run('op1');
  out.plain = { asked, n: calls.length };

  // Already confirmed once (newer-cloud route): a second refusal is not
  // answered by a second blind retry.
  replies = [DIV]; calls.length = 0; asked = 0; answer = true;
  api('c1', 'C:/x/a.esx', 'A', 'A', true);
  try { await enqueued.run('op1'); out.again = { threw: false }; }
  catch (err) { out.again = { threw: true, asked, n: calls.length }; }

  // Missing survey data: asked once, the retry carries the choice.
  const SHORT = { error: 'missing_survey_data', surveyGaps: 2, deletedOld: false };
  replies = [SHORT, { ok: true, newId: 'n1', oldId: 'c1', deletedOld: true }];
  calls.length = 0; asked = 0; answer = true;
  api('c1', 'C:/x/a.esx', 'A', 'A');
  await enqueued.run('op1');
  out.short = { asked, shorts: calls.map(c => c[5]), n: calls.length };

  replies = [SHORT]; calls.length = 0; asked = 0; answer = false;
  api('c1', 'C:/x/a.esx', 'A', 'A');
  try { await enqueued.run('op1'); out.shortNo = { threw: false }; }
  catch (err) { out.shortNo = { threw: true, asked, n: calls.length }; }

  // The row already asked: not asked a second time.
  replies = [{ ok: true, newId: 'n1', oldId: 'c1', deletedOld: true }];
  calls.length = 0; asked = 0; answer = true;
  api('c1', 'C:/x/a.esx', 'A', 'A', false, true);
  await enqueued.run('op1');
  out.shortRow = { asked, shorts: calls.map(c => c[5]) };
  console.log(JSON.stringify(out));
})().catch(err => { console.error(err.stack || String(err)); process.exit(1); });
"""


class ThePageAsksBeforeItSendsTheOverwriteTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not shutil.which("node"):
            raise unittest.SkipTest("node is not installed")
        d = Path(tempfile.mkdtemp(prefix="wd-diverged-node-"))
        try:
            script = d / "probe.js"
            script.write_text(NODE_SCRIPT, encoding="utf-8")
            r = subprocess.run(["node", str(script), str(CLOUD_JS)],
                               capture_output=True, encoding="utf-8",
                               timeout=NODE_TIMEOUT_S)
        finally:
            shutil.rmtree(d, True)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        cls.out = json.loads(r.stdout.strip().splitlines()[-1])

    def test_a_confirm_names_the_loss_and_then_sends_the_overwrite(self):
        self.assertEqual(1, self.out["yes"]["asked"])
        self.assertEqual(2, self.out["yes"]["n"])
        self.assertEqual([False, True], self.out["yes"]["flags"],
                         "the retry must carry the overwrite flag, the first "
                         "call must not")

    def test_declining_sends_nothing_further(self):
        no = self.out["no"]
        self.assertTrue(no["threw"], "a declined replace reported success")
        self.assertEqual(1, no["asked"])
        self.assertEqual(1, no["n"], "a declined replace sent another call")
        self.assertIn("Nothing was uploaded", no["msg"])

    def test_an_ordinary_replace_is_never_asked(self):
        self.assertEqual(0, self.out["plain"]["asked"])
        self.assertEqual(1, self.out["plain"]["n"])

    def test_missing_survey_data_is_asked_once_and_the_choice_travels(self):
        self.assertEqual(1, self.out["short"]["asked"])
        self.assertEqual([False, True], self.out["short"]["shorts"])

    def test_declining_the_missing_survey_data_question_sends_nothing(self):
        no = self.out["shortNo"]
        self.assertTrue(no["threw"])
        self.assertEqual(1, no["n"])

    def test_the_row_that_already_asked_is_not_asked_twice(self):
        self.assertEqual(0, self.out["shortRow"]["asked"])
        self.assertEqual([True], self.out["shortRow"]["shorts"])

    def test_an_already_confirmed_replace_is_not_asked_again(self):
        again = self.out["again"]
        self.assertTrue(again["threw"])
        self.assertEqual(0, again["asked"])
        self.assertEqual(1, again["n"])


if __name__ == "__main__":
    unittest.main()
