"""An edit the date inside the file does not record is still an edit.

"I edited a local copy of a cloud file and it's not showing as updated."

Every verdict in Cloud Manager - the row's staleness, the sync point's four
states, the pull's safe-direction guard - reads `history.modifiedAt` from
inside the .esx, on the premise that every save stamps it. A save that leaves
it alone was invisible to all three at once: the row read in step, and a pull
from the cloud was free to overwrite the edit, because the guard reads the
same date.

The sync point now carries the file's size on disk as well, and a size that
has moved while the date has not counts as a local change. These tests drive
the real download, the real listing and the real pull, and render the row
with the real function.

Every project, path and name here is invented.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools import sync_state as ss

ROOT = Path(__file__).resolve().parent.parent
CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
NODE_TIMEOUT_S = 120

ISO = "2026-08-01T08:00:00.000Z"
NAME = "SITE1 Riverside Baseline"


def _esx(path, extra_aps=0, iso=ISO):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("project.json", json.dumps({"project": {
            "id": "cloud-1", "name": NAME, "title": NAME,
            "history": {"modifiedAt": iso}}}))
        z.writestr("accessPoints.json", json.dumps({"accessPoints": [
            {"id": "ap-%d" % i, "name": "AP-%03d" % i}
            for i in range(extra_aps)]}))


class _Base(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-undated-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.state = self.tmp / "sync_state.json"
        real = ss.STATE_FILE
        ss.STATE_FILE = self.state
        self.addCleanup(lambda: setattr(ss, "STATE_FILE", real))

        from tools import cloud_manager as cm
        self.cm = cm
        cm._ESX_META_CACHE.clear()
        self.addCleanup(cm._ESX_META_CACHE.clear)

        self.root = self.tmp / "projects"
        (self.root / "SITE1 Riverside").mkdir(parents=True)
        buf = self.tmp / "_cloud.esx"
        _esx(buf)
        self.cloud_bytes = buf.read_bytes()
        self.cloud_mtime = cm._parse_cloud_mtime(
            {"history": {"modifiedAt": ISO}})

    def _mgr(self):
        blob = self.cloud_bytes

        class _Resp:
            status_code = 200

            def json(self_inner):
                return {"name": NAME, "history": {"modifiedAt": ISO}}

        class _Api:
            def get(self, url):
                return _Resp()

            def download_project(self, pid, progress_cb=None):
                return {"esx": blob, "name": NAME}

        mgr = self.cm.CloudManager.__new__(self.cm.CloudManager)
        mgr.config = {"output_dir": str(self.root)}
        mgr._ensure = lambda: True
        mgr.api = _Api()
        return mgr

    def _download(self):
        out = self._mgr().download_project("cloud-1", "SITE1 Riverside")
        self.assertTrue(out.get("ok"), out)
        return Path(out["path"])

    def _edit_without_moving_the_date(self, path):
        """What a save that does not stamp `modifiedAt` leaves behind."""
        _esx(path, extra_aps=40)
        self.cm._ESX_META_CACHE.clear()

    def _pair(self):
        cloud = [{"id": "cloud-1", "name": NAME, "code": "SITE1",
                  "mtime": self.cloud_mtime}]
        local = [{"path": f["path"], "name": f["name"], "code": "SITE1",
                  "isDir": False, "folder": f["folder"],
                  "size": int(f.get("size") or 0),
                  "mtime": int(f.get("mtime") or 0),
                  "projectId": f.get("projectId") or ""}
                 for f in self.cm.get_local_esx_files(str(self.root))]
        matched = self.cm.build_matches(cloud, local, set(), {})["matched"]
        self.assertEqual(1, len(matched), matched)
        return matched[0]


class ADownloadIsASyncPointTests(_Base):

    def test_a_download_records_the_pair_with_its_size(self):
        """Downloading is how local work usually starts. Without a note here
        an edit to a fresh download had nothing to be measured against."""
        path = self._download()
        rec = ss.load(_path=self.state).get("cloud-1")
        self.assertIsNotNone(rec, "the download wrote no sync point")
        self.assertEqual(path.stat().st_size, rec["localSize"])
        self.assertEqual(ss.IN_SYNC, ss.classify(
            rec, self.cloud_mtime, rec["localMtime"], str(path),
            path.stat().st_size))

    def test_a_fresh_download_reads_in_step(self):
        self._download()
        pr = self._pair()
        self.assertIsNone(pr["staleness"])
        self.assertEqual(ss.IN_SYNC, pr["divergence"])
        self.assertFalse(pr["localEditedUndated"])


class TheEditIsSeenTests(_Base):

    def test_the_row_says_local_newer(self):
        path = self._download()
        self._edit_without_moving_the_date(path)
        pr = self._pair()
        self.assertEqual(pr["local"]["mtime"], self.cloud_mtime,
                         "the probe must leave the date inside alone")
        self.assertEqual("local_newer", pr["staleness"])
        self.assertEqual(ss.LOCAL_CHANGED, pr["divergence"])
        self.assertTrue(pr["localEditedUndated"])

    def test_a_record_without_a_size_says_nothing_new(self):
        """Records written before this carry no size. Guessing from the
        filesystem date instead would flag every file a sync client touched,
        and a false "edited" refuses a pull."""
        rec = {"localPath": "p", "cloudMtime": 1000, "localMtime": 1000}
        self.assertFalse(ss.edited_in_place(rec, "p", 1000, 12345))
        self.assertEqual(ss.IN_SYNC, ss.classify(rec, 1000, 1000, "p", 12345))

    def test_a_moved_date_is_left_to_the_dates(self):
        rec = {"localPath": "p", "cloudMtime": 1000, "localMtime": 1000,
               "localSize": 10}
        self.assertFalse(ss.edited_in_place(rec, "p", 5000, 99))
        self.assertEqual(ss.LOCAL_CHANGED, ss.classify(rec, 1000, 5000, "p", 99))

    def test_both_sides_moving_is_still_both(self):
        rec = {"localPath": "p", "cloudMtime": 1000, "localMtime": 1000,
               "localSize": 10}
        self.assertEqual(ss.BOTH_CHANGED, ss.classify(rec, 5000, 1000, "p", 99))

    def test_a_stored_comparison_is_retired_by_the_edit(self):
        """Otherwise "same design" from before the edit stays on the row."""
        ss.record_comparison("cloud-1", "p", 1000, 1000,
                             {"identical": True, "designDiffers": False},
                             _path=self.state, local_size=10)
        pairs = ss.load(_path=self.state)
        self.assertIsNotNone(ss.comparison_for(pairs, "cloud-1", "p",
                                               1000, 1000, 10))
        self.assertIsNone(ss.comparison_for(pairs, "cloud-1", "p",
                                            1000, 1000, 11))


class APullDoesNotOverwriteItTests(_Base):

    def test_the_pull_refuses_and_leaves_the_file_alone(self):
        path = self._download()
        self._edit_without_moving_the_date(path)
        before = path.read_bytes()
        out = self._mgr().verify_replace_local("cloud-1", str(path))
        self.assertEqual("local_newer", out.get("error"), out)
        self.assertEqual(before, path.read_bytes(),
                         "the pull overwrote an edit it had just refused")

    def test_an_untouched_file_still_pulls(self):
        """The refusal must be evidence-gated, not a wall across the road."""
        path = self._download()
        out = self._mgr().verify_replace_local("cloud-1", str(path))
        self.assertFalse(out.get("error"), out)
        self.assertEqual(path.stat().st_size,
                         ss.load(_path=self.state)["cloud-1"]["localSize"])


NODE_SCRIPT = r"""
const fs = require('fs');
const source = fs.readFileSync(process.argv[process.argv.length - 1], "utf8");
function slice(from, to) {
  const a = source.indexOf(from);
  const b = source.indexOf(to, a);
  if (a < 0 || b < 0) throw new Error('could not find ' + from);
  return source.slice(a, b);
}
const block = slice('function ownershipBlock(', '\nfunction _isExternal(')
            + slice('function comparisonIsSettled(', '\nfunction isOutOfSync(')
            + slice('const ICONS = {', '\nfunction siteDigest(')
            + slice('const MATCH_BADGE_SPEC = {', '\nfunction gutCell(r)');
const WD = { esc: s => String(s == null ? '' : s),
             escAttr: s => String(s == null ? '' : s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;'),
             escJsStr: s => String(s == null ? '' : s) };
function e(s) { return WD.esc(s); }
function a(s) { return WD.escAttr(s); }
function np(s) { return String(s == null ? '' : s).replace(/\\/g, '/'); }
function p(s) { return a(np(s)); }
const noop = () => {};
const fn = new Function('WD','e','a','p','np','currentTab','opEnqueue','toast','pyApi','showConfirmModal','_clearStaleness','_scheduleOpRefresh','selectedSyncItems','clearSelection','renderRows',
  block + '\nreturn { rowDetailHtml };');
const api = fn(WD,e,a,p,np,'projects',noop,noop,async()=>({}),async()=>true,noop,noop,()=>[],noop,noop);
const row = (undated) => ({
  kind: 'projects', matchType: 'id', staleness: 'local_newer',
  differenceKind: 'content', localEditedUndated: undated,
  cloud: { id: 'c1', name: 'SITE1 Riverside Baseline', mtime: 100 },
  local: { path: 'C:/projects/SITE1/SITE1 Riverside Baseline.esx',
           name: 'SITE1 Riverside Baseline', mtime: 100 },
});
console.log(JSON.stringify({ undated: api.rowDetailHtml(row(true), false),
                             dated: api.rowDetailHtml(row(false), false) }));
"""


class TheRowSaysWhatHappenedTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        if not shutil.which("node"):
            raise unittest.SkipTest("node is not installed")
        r = subprocess.run(["node", "-e", NODE_SCRIPT, str(CLOUD_JS)],
                           capture_output=True, encoding="utf-8",
                           timeout=NODE_TIMEOUT_S)
        if r.returncode != 0:
            raise AssertionError((r.stdout + r.stderr).strip())
        cls.out = json.loads(r.stdout)

    def test_it_does_not_claim_a_later_date_it_does_not_have(self):
        """Both dates on this row are the same; "later date" would be false."""
        self.assertNotIn("later date", self.out["undated"])
        self.assertIn("date inside it did not change", self.out["undated"])

    def test_an_ordinary_local_newer_row_is_unchanged(self):
        self.assertIn("later date", self.out["dated"])
        self.assertNotIn("date inside it did not change", self.out["dated"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
