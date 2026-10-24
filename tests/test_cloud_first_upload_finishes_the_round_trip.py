"""A new local file goes up, lands in its site, and comes back with Ekahau's id.

The round trip is five steps: upload, find the new project, rename it to the
file's name, file it into the site, then download the cloud copy over the local
file so the id Ekahau assigned is inside it. Each step after the upload asks a
different Ekahau service about a project it has only just processed, and the
first ask is the one most likely to be refused. A refusal used to end the step
for good: the project stayed unassigned, or the local file never received its
id.

The sync-back also left no record that the two sides were now the same, which
the replace path has always written, so a first upload was the one operation
that finished without settling the row.

Only Ekahau's HTTP surface is faked; the real retry, the real rename, the real
sync-back and the real sync-point store run. Every name here is invented.
"""
from __future__ import annotations

import unittest

from tools import cloud_manager as cm
from tools import sync_state

from tests.test_cloud_upload_identifies_what_it_made import (
    FILE_STEM, _Base, _StubEkahau)


class _Refusing(_StubEkahau):
    """Refuses the first `n` calls of a step, the way a project that is listed
    but not yet visible to the site service or the batch download does."""

    def __init__(self, *, assign_refusals=0, download_refusals=0,
                 rename_fails=False, **kw):
        super().__init__(**kw)
        self.assign_refusals = assign_refusals
        self.download_refusals = download_refusals
        self.rename_fails = rename_fails
        self.assign_calls = 0
        self.download_calls = 0

    def assign_to_site(self, site_id, dataset_id, dtype=None):
        self.assign_calls += 1
        if self.assign_calls <= self.assign_refusals:
            raise RuntimeError("404 dataset not found yet")
        return super().assign_to_site(site_id, dataset_id, dtype)

    def download_project(self, pid, progress_cb=None):
        self.download_calls += 1
        if self.download_calls <= self.download_refusals:
            raise RuntimeError("409 project not ready")
        return super().download_project(pid, progress_cb)

    def rename_project(self, pid, name):
        if self.rename_fails:
            raise RuntimeError("403 cannot rename")
        return super().rename_project(pid, name)


class _Round(_Base):
    def setUp(self):
        super().setUp()
        sync_state.prune([])

    def run_upload(self, **kw):
        api = _Refusing(**kw)

        class M(cm.CloudManager):
            def __init__(s):
                s.api = api
                s.config = {"output_dir": str(self.root)}

            def _ensure(s):
                return True

        return M().upload_project(str(self.esx), "site-9"), api


class AStepRefusedOnceIsAskedAgain(_Round):
    def test_a_site_refusal_does_not_leave_the_project_unassigned(self):
        out, api = self.run_upload(assign_refusals=2)
        self.assertTrue(out.get("assigned"), out)
        self.assertEqual([("site-9", "new-1")], api.assigned)
        self.assertEqual(3, api.assign_calls)
        self.assertNotIn("assignError", out)

    def test_a_download_refusal_does_not_leave_the_local_file_without_its_id(self):
        out, api = self.run_upload(download_refusals=2)
        self.assertTrue(out.get("syncedBack"), out)
        self.assertNotIn("syncBackError", out)
        self.assertEqual(3, api.download_calls)
        self.assertNotEqual(self.original, self.esx.read_bytes(),
                            "the cloud copy was never written over the local file")

    def test_a_step_that_keeps_refusing_is_still_reported(self):
        out, api = self.run_upload(assign_refusals=99)
        self.assertIn("404", out.get("assignError", ""), out)
        self.assertTrue(out.get("warning"), out)
        # The download is independent of the assignment and still runs.
        self.assertTrue(out.get("syncedBack"), out)

    def test_a_download_that_keeps_failing_names_the_reason_and_keeps_the_file(self):
        out, api = self.run_upload(download_refusals=99)
        self.assertIn("409", out.get("syncBackError", ""), out)
        self.assertEqual(self.original, self.esx.read_bytes())


class TheFirstUploadSettlesTheRow(_Round):
    def test_the_sync_point_is_recorded_under_the_new_id(self):
        out, api = self.run_upload()
        self.assertTrue(out.get("syncedBack"), out)
        entry = sync_state.load().get("new-1")
        self.assertIsNotNone(entry, "the first upload left no sync point")
        self.assertEqual(str(self.esx), entry["localPath"])

    def test_no_sync_point_when_nothing_was_written_back(self):
        out, api = self.run_upload(download_refusals=99)
        self.assertNotIn("new-1", sync_state.load(),
                         "claimed the sides were the same when they are not")


class ARenameThatFailsIsSaid(_Round):
    def test_the_failure_is_in_the_result(self):
        out, api = self.run_upload(rename_fails=True)
        self.assertIn("403", out.get("renameError", ""), out)
        self.assertTrue(out.get("warning"), out)
        self.assertTrue(out.get("assigned"), "the rename failing stopped the rest")

    def test_a_rename_that_works_reports_nothing(self):
        out, api = self.run_upload()
        self.assertEqual(FILE_STEM, out.get("renamedTo"), out)
        self.assertNotIn("renameError", out)


if __name__ == "__main__":
    unittest.main()
