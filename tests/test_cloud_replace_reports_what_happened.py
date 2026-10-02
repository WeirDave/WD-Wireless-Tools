"""A replace has to record, and say, what actually happened.

Four defects in `replace_cloud_project`, each green before because nothing ran
the operation and then read back what it left behind:

* **The sync point named the wrong cloud date.** It read
  `check["project"]` from `_verify_uploaded`, which never returned one, so the
  cloud side of the note was the local file's disk time. The next local-only
  edit then read as *both sides changed*, and Sync everything filed the pair
  under "diverged" and refused to push it again.
* **The upload's partial failures were dropped.** A project left out of its
  site, or a local file never synced back, came back as a plain success, with
  the old `siteId` reported as though the new one were filed there, and a sync
  point recorded for a sync-back that did not happen.
* **Ownership was never asked.** Proven somebody else's, the replace uploaded
  anyway and only found out at the delete - leaving a duplicate behind.
* **The page dropped `warning`.** Even passed through, the toast never said it.

Ekahau is stubbed at its HTTP surface, as in
`test_cloud_replace_reads_what_the_upload_returns.py`; the real
`upload_project` and `_verify_uploaded` run. Every name and address invented.
"""
from __future__ import annotations

import io
import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tools import cloud_manager as cm
from tools import sync_state as ss

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 120

ME = "survey.lead@example.invalid"
#: What Ekahau reports for the project the upload creates. Deliberately not
#: the local file's disk time, which is what the defect recorded instead.
CLOUD_NEW_MOD = "2026-09-20T10:00:00Z"
LOCAL_MOD = "2026-09-15T00:00:00Z"


def _esx_bytes(pid: str, name: str, modified: str, extra: str = "") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("project.json", json.dumps({"project": {
            "id": pid, "name": name, "description": extra,
            "history": {"createdBy": ME, "modifiedAt": modified}}}))
    return buf.getvalue()


class _StubEkahau:
    """The calls `replace_cloud_project` makes, answered as Ekahau answers.

    Shares and ownership live only in the dataset listing's `datasetUsers`,
    because that is the only place the real API puts them.
    """

    user_email = ME

    def __init__(self, *, owner=ME, assign_fails=False, download_fails=False):
        self.projects = [{"id": "old-1", "name": "Alder Court",
                          "history": {"modifiedAt": "2026-09-01T00:00:00Z"}}]
        self.datasets = [{"id": "old-1", "siteId": "site-4", "datasetUsers": [
            {"role": "OWNER", "username": owner}]}]
        self.uploaded, self.deleted, self.assigned = [], [], []
        self._pending = None
        self._assign_fails = assign_fails
        self._download_fails = download_fails

    def get_projects(self):
        if self._pending:
            self.projects.append(self._pending)
            self._pending = None
        return [dict(p) for p in self.projects]

    def get_dataset_listing(self):
        return [json.loads(json.dumps(d)) for d in self.datasets]

    def list_project_shares(self, pid):
        return {}

    def upload_project(self, esx_path, progress_cb=None):
        self.uploaded.append(str(esx_path))
        self._pending = {"id": "new-1", "name": "Alder Court",
                         "history": {"modifiedAt": CLOUD_NEW_MOD}}
        return {"ok": True, "status": 200}

    def download_project(self, pid, progress_cb=None):
        if self._download_fails:
            raise RuntimeError("storage timed out")
        return {"esx": _esx_bytes(pid, "Alder Court", CLOUD_NEW_MOD),
                "name": "Alder Court"}

    def rename_project(self, pid, name):
        return {"ok": True}

    def assign_to_site(self, site_id, dataset_id, dtype=None):
        if self._assign_fails:
            raise RuntimeError("403 not permitted")
        self.assigned.append((site_id, dataset_id))
        return {"ok": True}

    def delete_project(self, pid):
        self.deleted.append(pid)
        self.projects = [p for p in self.projects if p["id"] != pid]
        return {"ok": True}


class _Manager(cm.CloudManager):
    def __init__(self, api, out_dir):
        self.api = api
        self.config = {"output_dir": str(out_dir)}

    def _ensure(self):
        return True


class _Base(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.esx = self.root / "Alder" / "Alder Court.esx"
        self.esx.parent.mkdir(parents=True)
        self.esx.write_bytes(_esx_bytes("local-1", "Alder Court", LOCAL_MOD))
        real = ss.STATE_FILE
        ss.STATE_FILE = self.root / "sync_state.json"
        self.addCleanup(lambda: setattr(ss, "STATE_FILE", real))
        p = mock.patch.object(cm.time, "sleep", lambda *_a, **_k: None)
        p.start()
        self.addCleanup(p.stop)

    def _run(self, **kw):
        api = _StubEkahau(**kw)
        out = _Manager(api, self.root).replace_cloud_project(
            str(self.esx), "old-1")
        return out, api

    def _row(self, api):
        """The pair as the list builds it: real listing date, real disk scan."""
        listing = {p["id"]: p for p in api.get_projects()}
        cloud = [{"id": "new-1", "name": "Alder Court",
                  "mtime": cm._parse_cloud_mtime(listing["new-1"])}]
        local = cm.get_local_esx_files(str(self.root))
        res = cm.build_matches(cloud, local)
        self.assertEqual(1, len(res["matched"]), res)
        return res["matched"][0]


class APushedPairStaysInStepTests(_Base):

    def test_right_after_the_replace_the_pair_is_in_sync(self):
        out, api = self._run()
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(ss.IN_SYNC, self._row(api)["divergence"])

    def test_a_local_edit_afterwards_reads_as_local_changed_not_both(self):
        """The defect as he would meet it: edit locally, and Sync everything
        calls the pair diverged and will not push it."""
        out, api = self._run()
        self.assertTrue(out.get("ok"), out)
        # A different size as well as a later date: an edit landing in the
        # same second at the same size is a cache question, not this one.
        self.esx.write_bytes(_esx_bytes("new-1", "Alder Court",
                                        "2026-09-21T10:00:00Z",
                                        extra="one more access point"))
        self.assertEqual(ss.LOCAL_CHANGED, self._row(api)["divergence"])

    def test_the_recorded_cloud_date_is_the_listings(self):
        out, api = self._run()
        self.assertTrue(out.get("ok"), out)
        listing = {p["id"]: p for p in api.get_projects()}
        self.assertEqual(cm._parse_cloud_mtime(listing["new-1"]),
                         ss.load()["new-1"]["cloudMtime"])


class ThePartialFailuresAreSaidTests(_Base):

    def test_a_failed_site_assignment_is_reported_and_not_claimed(self):
        out, api = self._run(assign_fails=True)
        self.assertTrue(out.get("ok"), out)
        self.assertIn("403 not permitted", out.get("assignError") or "")
        self.assertIsNone(out.get("siteId"),
                          "reported the old site for an unfiled project")
        self.assertIn("site", (out.get("warning") or "").lower())

    def test_a_successful_assignment_still_reports_the_site(self):
        out, api = self._run()
        self.assertEqual("site-4", out.get("siteId"))
        self.assertEqual([("site-4", "new-1")], api.assigned)
        self.assertIsNone(out.get("warning"))

    def test_a_failed_sync_back_is_reported_and_not_recorded(self):
        out, api = self._run(download_fails=True)
        self.assertTrue(out.get("ok"), out)
        self.assertIn("storage timed out", out.get("syncBackError") or "")
        self.assertIn("downloaded back", out.get("warning") or "")
        self.assertNotIn("new-1", ss.load(),
                         "recorded the pair in step after a failed sync-back")


class SomebodyElsesProjectIsRefusedTests(_Base):

    def test_a_project_owned_by_someone_else_is_not_uploaded_over(self):
        out, api = self._run(owner="other.owner@example.invalid")
        self.assertFalse(out.get("ok"))
        self.assertEqual("ownership", out.get("step"))
        self.assertEqual([], api.uploaded, "uploaded before refusing")
        self.assertEqual([], api.deleted)
        self.assertIn("other.owner@example.invalid", out.get("error") or "")

    def test_an_unproven_owner_is_still_attempted(self):
        """Only proof refuses - an unreadable owner is not evidence."""
        out, api = self._run(owner="")
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(["old-1"], api.deleted)


def _node_program() -> str:
    return r"""
const fs = require('fs');
const src = fs.readFileSync(process.argv[1], 'utf8');
const a = src.indexOf('function _enqueuePushLocalOverCloud(');
if (a < 0) throw new Error('_enqueuePushLocalOverCloud moved');
let b = a, depth = 0, seen = false;
while (b < src.length && !(seen && depth === 0)) {
  if (src[b] === '{') { depth++; seen = true; }
  else if (src[b] === '}') depth--;
  b++;
}
const toasts = [];
function toast(msg, kind) { toasts.push([String(msg), kind]); }
function _setRowBusy() {}
function _clearStaleness() {}
function _scheduleOpRefresh() {}
function settlePair() { return Promise.resolve(); }
let runner = null;
function opEnqueue(o) { runner = o.run; return { promise: new Promise(() => {}) }; }
async function pyApi() { return JSON.parse(process.argv[2]); }
eval(src.slice(a, b));
(async () => {
  _enqueuePushLocalOverCloud('new-1', 'D:/x/Alder Court.esx', 'Alder Court', 'Alder Court');
  if (!runner) throw new Error('nothing was enqueued');
  await runner('op-1');
  process.stdout.write(JSON.stringify(toasts));
})().catch(e => { console.error(e && e.stack || e); process.exit(1); });
"""


@unittest.skipUnless(shutil.which("node"), "Node.js is not installed")
class ThePageSaysTheWarningTests(unittest.TestCase):

    def _toasts(self, result: dict):
        r = subprocess.run(
            ["node", "-e", _node_program(), str(CLOUD_JS), json.dumps(result)],
            capture_output=True, text=True, encoding="utf-8",
            timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        return json.loads(r.stdout)

    def test_a_warning_on_a_successful_replace_is_shown(self):
        warning = ("The new copy is in the cloud, but it could not be put in "
                   "the old project's site (403).")
        toasts = self._toasts({"ok": True, "name": "Alder Court",
                               "deletedOld": True, "warning": warning})
        self.assertIn([warning, "warn"], toasts, toasts)

    def test_no_warning_no_extra_toast(self):
        toasts = self._toasts({"ok": True, "name": "Alder Court",
                               "deletedOld": True})
        self.assertEqual(["success"], [k for _m, k in toasts], toasts)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
