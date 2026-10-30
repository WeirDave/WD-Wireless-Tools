"""Work saved while Cloud Manager is busy is not replaced by an older copy,
and a delete that did not finish does not say it did.

A transfer runs for seconds to minutes and the decision to overwrite the local
file is made at the start. Ekahau saving into the same file in between is the
ordinary way to lose work, and nothing re-checked: the pull compared dates once
and wrote after a whole download, and the upload's read-back wrote the cloud
copy over the file after a wait that can reach minutes.

Four independent things are asserted, each from a way the tool could lie:

* a pull whose local file changed during the download leaves it alone;
* an upload whose local file changed during the upload does not write the
  cloud copy over it, and still counts as read back (the proof the replace
  waits for), and a replace without that proof deletes nothing;
* a read-back write that fails leaves no full-size temporary file in a
  synced folder;
* `delete_local` on a folder it could only half empty says so, and never
  deletes the folder every site lives in.

Every name here is invented; nothing contacts Ekahau; every file is in a
temporary directory that is removed afterwards.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import cloud_manager as cm  # noqa: E402
from tools import sync_state  # noqa: E402

from tests.test_cloud_first_upload_finishes_the_round_trip import (  # noqa: E402
    _Refusing, _Round)

LOCAL_OLD = "2026-08-01T08:00:00.000Z"
CLOUD_NEW = "2026-09-04T08:00:00.000Z"


def _esx(path: Path, modified_iso: str, aps=(1,)):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project.json", json.dumps({"project": {
            "id": "proj-1", "name": path.stem, "title": path.stem,
            "history": {"modifiedAt": modified_iso}}}))
        z.writestr("accessPoints.json", json.dumps({"accessPoints": [
            {"id": "ap-%d" % i} for i in aps]}))
        z.writestr("floorPlans.json", json.dumps({"floorPlans": []}))


class _Resp:
    status_code = 200

    def __init__(self, payload):
        self._p = payload

    def json(self):
        return self._p


class APullThatSawTheFileChangeLeavesItAloneTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-meanwhile-pull-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        cm._ESX_META_CACHE.clear()
        self.addCleanup(cm._ESX_META_CACHE.clear)
        self.local = self.tmp / "Example Survey.esx"
        _esx(self.local, LOCAL_OLD)
        cloud = self.tmp / "_cloud.esx"
        _esx(cloud, CLOUD_NEW, aps=(1, 2))
        self.cloud_bytes = cloud.read_bytes()
        cloud.unlink()

    def _pull(self, during_download=None):
        mgr = cm.CloudManager.__new__(cm.CloudManager)
        mgr.config = {"output_dir": str(self.tmp)}
        mgr._ensure = lambda: True
        cloud_bytes = self.cloud_bytes

        class Api:
            def get(self, url):
                return _Resp({"name": "Example Survey",
                              "modifiedAt": CLOUD_NEW})

            def download_project(self, pid, progress_cb=None):
                if during_download:
                    during_download()
                return {"esx": cloud_bytes}
        mgr.api = Api()
        return mgr.verify_replace_local("cloud-1", str(self.local))

    def test_a_save_during_the_download_is_not_replaced(self):
        saved = {}

        def ekahau_saves():
            _esx(self.local, LOCAL_OLD, aps=(1, 2, 3, 4, 5))
            saved["bytes"] = self.local.read_bytes()

        res = self._pull(during_download=ekahau_saves)

        self.assertIn("error", res, res)
        self.assertIn("saved while", res["error"])
        self.assertEqual(saved["bytes"], self.local.read_bytes(),
                         "the file saved during the download was overwritten")
        self.assertEqual([self.local], list(self.tmp.iterdir()),
                         "a refused pull left a file behind")

    def test_an_untouched_file_is_still_replaced(self):
        """The check must not refuse the ordinary pull."""
        res = self._pull()
        self.assertTrue(res.get("ok"), res)
        self.assertEqual(self.cloud_bytes, self.local.read_bytes())


class AnUploadThatSawTheFileChangeKeepsItTests(_Round):

    def test_a_save_during_the_upload_is_not_overwritten_but_is_read_back(self):
        saved = {}

        class Saving(_Refusing):
            def download_project(s, pid, progress_cb=None):
                self.esx.write_bytes(self.original + b"-an edit made meanwhile")
                saved["bytes"] = self.esx.read_bytes()
                return super().download_project(pid, progress_cb)

        api = Saving()
        mgr = cm.CloudManager.__new__(cm.CloudManager)
        mgr.api = api
        mgr.config = {"output_dir": str(self.root)}
        mgr._ensure = lambda: True

        out = mgr.upload_project(str(self.esx), "site-9")

        self.assertTrue(out.get("readBack"), out)
        self.assertFalse(out.get("syncedBack"), out)
        self.assertIn("saved while", out.get("syncBackError", ""), out)
        self.assertEqual(saved["bytes"], self.esx.read_bytes(),
                         "the cloud copy was written over a file saved "
                         "during the upload")
        self.assertNotIn("new-1", sync_state.load(),
                         "claimed the sides were the same when they are not")

    def test_a_failed_write_back_leaves_no_temporary_file(self):
        with mock.patch.object(cm.os, "replace",
                               side_effect=PermissionError("in use")):
            out, api = self.run_upload()
        self.assertIn("in use", out.get("syncBackError", ""), out)
        self.assertEqual([], sorted(p.name for p in self.root.rglob("*.tmp")),
                         "a full-size temp file was left in the folder")
        self.assertEqual(self.original, self.esx.read_bytes())


class AReplaceWithoutAReadBackDeletesNothingTests(unittest.TestCase):

    def test_an_upload_that_was_never_read_back_keeps_the_old_project(self):
        from tests.test_cloud_replace_project import _Manager, _StubApi, _esx as _e
        root = Path(tempfile.mkdtemp(prefix="wd-meanwhile-replace-"))
        self.addCleanup(shutil.rmtree, root, True)
        esx = _e(root / "Alpha Survey.esx")
        api = _StubApi()
        mgr = _Manager(api, root)

        def upload(path, site_id=None, progress_cb=None):
            api.projects.append({"id": "new-1", "name": "Alpha Survey"})
            return {"ok": True, "uploaded": True, "datasetId": "new-1",
                    "syncBackError": "Failed fetching survey track"}
        mgr.upload_project = upload

        out = mgr.replace_cloud_project(str(esx), "old-1")

        self.assertEqual("readback", out.get("step"), out)
        self.assertFalse(out.get("deletedOld"))
        self.assertEqual([], api.deleted,
                         "the old project was deleted over an unread upload")
        self.assertIn("Failed fetching survey track", out.get("error", ""))
        self.assertTrue(any(p["id"] == "old-1" for p in api.projects))


class ADeleteTellsTheTruthTests(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="wd-meanwhile-delete-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        self.site = self.root / "Example Site"
        self.site.mkdir()
        (self.site / "a.esx").write_bytes(b"a")
        (self.site / "b.esx").write_bytes(b"b")
        self.mgr = cm.CloudManager.__new__(cm.CloudManager)
        self.mgr.config = {"output_dir": str(self.root)}

    def test_the_folder_every_site_lives_in_is_never_deleted(self):
        res = self.mgr.delete_local(str(self.root))
        self.assertIn("error", res, res)
        self.assertTrue((self.site / "a.esx").exists())
        self.assertTrue((self.site / "b.esx").exists())

    def test_the_folder_every_site_lives_in_is_never_renamed(self):
        res = self.mgr.rename_local(str(self.root), "Renamed")
        self.assertIn("error", res, res)
        self.assertTrue(self.root.exists())

    def test_a_folder_only_half_emptied_is_not_reported_as_deleted(self):
        """A file another program holds open survives `rmtree`, whose error
        hook swallows the refusal. The call used to return ok over a folder
        with one project still in it."""
        def half(path, onerror=None):
            Path(path, "a.esx").unlink()
        with mock.patch.object(cm.shutil, "rmtree", half):
            res = self.mgr.delete_local(str(self.site))
        self.assertNotIn("ok", res, res)
        self.assertIn("error", res)
        self.assertEqual(1, res.get("remaining"))
        self.assertTrue((self.site / "b.esx").exists())

    def test_a_folder_that_goes_completely_is_ok(self):
        res = self.mgr.delete_local(str(self.site))
        self.assertTrue(res.get("ok"), res)
        self.assertFalse(self.site.exists())


class AFileMissingItsSurveySamplesDoesNotReplaceTheProjectThatHasThemTests(
        unittest.TestCase):
    """The row asked before replacing the cloud project with a file whose
    surveys point at samples it no longer holds; the bulk Sync paths did not,
    so the same file was refused one way and sent the other, and the cloud
    project that may be the only copy of the samples was deleted. The server is
    the one place every route passes."""

    def setUp(self):
        from tests.test_cloud_replace_project import _Manager, _StubApi
        self.root = Path(tempfile.mkdtemp(prefix="wd-meanwhile-survey-"))
        self.addCleanup(shutil.rmtree, self.root, True)
        cm._ESX_META_CACHE.clear()
        self.addCleanup(cm._ESX_META_CACHE.clear)
        self.esx = self.root / "Alpha Survey.esx"
        with zipfile.ZipFile(self.esx, "w") as z:
            z.writestr("project.json", json.dumps({"project": {
                "id": "local-uuid-1", "history": {"modifiedAt": ""}}}))
            z.writestr("survey-s1.json", json.dumps({"surveys": [{
                "id": "s1", "wifiTracks": [{"binaryFileId": "t1"}]}]}))
            # track-t1.bin is deliberately absent
        self.api = _StubApi()
        self.mgr = _Manager(self.api, self.root)
        self.uploads = 0

        def upload(path, site_id=None, progress_cb=None):
            self.uploads += 1
            self.api.projects.append({"id": "new-1", "name": "Alpha Survey"})
            return {"ok": True, "uploaded": True, "datasetId": "new-1",
                    "readBack": True}
        self.mgr.upload_project = upload

    def test_it_is_refused_before_anything_is_uploaded(self):
        out = self.mgr.replace_cloud_project(str(self.esx), "old-1")
        self.assertEqual("missing_survey_data", out.get("error"), out)
        self.assertEqual(1, out.get("surveyGaps"))
        self.assertEqual(0, self.uploads, "uploaded before refusing")
        self.assertEqual([], self.api.deleted)

    def test_the_confirmed_replace_goes_through(self):
        out = self.mgr.replace_cloud_project(
            str(self.esx), "old-1", allow_missing_survey_data=True)
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(["old-1"], self.api.deleted)

    def test_a_complete_file_is_not_asked_about(self):
        with zipfile.ZipFile(self.esx, "a") as z:
            z.writestr("track-t1.bin", b"samples")
        cm._ESX_META_CACHE.clear()
        out = self.mgr.replace_cloud_project(str(self.esx), "old-1")
        self.assertTrue(out.get("ok"), out)


class AFileThatIsNotWholeIsNotUploadedTests(unittest.TestCase):
    """An upload of a file Ekahau is still writing, or one a sync client cut
    short, "succeeds" - and a replace then deletes the good cloud project on
    the strength of it. The archive is opened before a slot is requested."""

    def _api(self):
        api = cm.EkahauAPI.__new__(cm.EkahauAPI)
        api.asked = 0

        def write(method, path, body=None):
            api.asked += 1
            raise AssertionError("asked Ekahau for an upload slot")
        api._write = write
        return api

    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="wd-meanwhile-whole-"))
        self.addCleanup(shutil.rmtree, self.root, True)

    def test_a_truncated_archive_is_refused_before_any_request(self):
        good = self.root / "good.esx"
        _esx(good, LOCAL_OLD)
        cut = self.root / "Cut Short.esx"
        cut.write_bytes(good.read_bytes()[:60])
        api = self._api()
        out = api.upload_project(str(cut))
        self.assertIn("error", out, out)
        self.assertIn("not uploaded", out["error"])
        self.assertEqual(0, api.asked)

    def test_an_archive_with_no_project_record_is_refused(self):
        f = self.root / "Empty.esx"
        with zipfile.ZipFile(f, "w") as z:
            z.writestr("notes.txt", "x")
        api = self._api()
        out = api.upload_project(str(f))
        self.assertIn("no project record", out.get("error", ""), out)
        self.assertEqual(0, api.asked)


if __name__ == "__main__":
    unittest.main()
