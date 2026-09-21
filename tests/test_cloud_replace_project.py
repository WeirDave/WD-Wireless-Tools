"""Uploading a local .esx over an existing cloud project.

"why can't we just automatically delete that first and then upload the new one?
I mean why do we have to consider that we can only do one step at a time?"

Composing the calls is right. **The order is inverted from the way he said it**,
and that inversion is what most of this file is about:

* **Delete first** and a failed upload leaves *nothing* in the cloud. His local
  copy survives, but the shared copy other people work from is gone, and he may
  not find out until somebody asks for it.
* **Upload first** and a failure leaves a duplicate - visible, annoying, and
  removable in one click.

So the old project is not touched until the new one is confirmed present *and*
confirmed to be the file he just sent. And when the delete is the step that
fails, the result says there are two and which one is new, because he has been
burned by duplicates twice and a silent failure is the one he cannot survive.

**Ekahau is never contacted here.** Every call is against a stub, and every
project name is invented.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools import cloud_manager as cm


def _esx(path: Path, project_id: str = "local-uuid-1"):
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"project": {"id": project_id,
                       "history": {"createdBy": "me@example.com",
                                   "modifiedAt": ""}}}
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project.json", json.dumps(doc))
    return path


class _StubApi:
    """Ekahau, as far as this operation is concerned."""

    def __init__(self, *, upload_ok=True, appears=True, delete_raises=False):
        self.projects = [{"id": "old-1", "name": "Alpha Survey"}]
        self.datasets = [{"id": "old-1", "siteId": "site-9"}]
        self.deleted = []
        self.uploaded = []
        #: Every call in the order it arrived. `deleted` and `uploaded` record
        #: *that* something happened; the order is the safety property, and
        #: nothing recorded it until the A34 conversion.
        self.calls = []
        self._upload_ok = upload_ok
        self._appears = appears
        self._delete_raises = delete_raises

    # -- reads ---------------------------------------------------------
    def get_projects(self):
        self.calls.append("verify")
        return list(self.projects)

    def get_dataset_listing(self):
        self.calls.append("list")
        return list(self.datasets)

    # -- writes --------------------------------------------------------
    def upload_project(self, esx_path, progress_cb=None):
        self.calls.append("upload")
        if not self._upload_ok:
            return {"error": "network went away"}
        self.uploaded.append(str(esx_path))
        if self._appears:
            self.projects.append({"id": "new-1", "name": Path(esx_path).stem})
        return {"ok": True}

    def delete_project(self, pid):
        self.calls.append("delete")
        if self._delete_raises:
            raise RuntimeError("403 refused")
        self.deleted.append(pid)
        self.projects = [p for p in self.projects if p["id"] != pid]
        return {"ok": True}

    def rename_project(self, pid, name):
        for p in self.projects:
            if p["id"] == pid:
                p["name"] = name
        return {"ok": True}

    def assign_to_site(self, site_id, dataset_id, dtype=None):
        return {"ok": True}


class _Manager(cm.CloudManager):
    def __init__(self, api, out_dir):
        self.api = api
        self.config = {"output_dir": str(out_dir)}

    def _ensure(self):
        return True


class ReplacingAnExistingCloudProjectTests(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.esx = _esx(self.root / "Alpha Survey.esx")

    def _mgr(self, **kw):
        api = _StubApi(**kw)
        mgr = _Manager(api, self.root)

        # The manager's own `upload_project` does its own listing poll and
        # rename; what is under test here is the composition around it, so it
        # is replaced with something that succeeds or fails on cue.
        #
        # **It has to return the shape the real one returns.** This stub said
        # `{"ok": True, "id": "new-1"}`, and the real function publishes the
        # new project under `datasetId`. So these tests passed for a year
        # against a contract nothing implemented, while the first real run of
        # Local -> Cloud stopped at "the new project could not be identified"
        # for every file, every time. A stub that invents the contract tests
        # the stub.
        #
        # The end-to-end version, with only Ekahau faked, is
        # `tests/test_cloud_replace_reads_what_the_upload_returns.py`.
        def fake_upload(path, site_id=None, progress_cb=None):
            result = api.upload_project(path)
            if result.get("error"):
                return result
            return {"ok": True, "uploaded": True, "datasetId": "new-1"}

        mgr.upload_project = fake_upload
        return mgr, api

    def test_the_old_project_is_deleted_only_after_the_upload(self):
        mgr, api = self._mgr()
        out = mgr.replace_cloud_project(str(self.esx), "old-1")
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(["old-1"], api.deleted)
        self.assertTrue(api.uploaded, "nothing was uploaded")

    def test_a_failed_upload_deletes_nothing(self):
        """The whole reason for the inverted order.

        Delete-then-upload would have left his cloud empty here.
        """
        mgr, api = self._mgr(upload_ok=False)
        out = mgr.replace_cloud_project(str(self.esx), "old-1")
        self.assertIn("error", out)
        self.assertFalse(out.get("deletedOld"))
        self.assertEqual([], api.deleted)
        self.assertIn("Nothing was deleted", out["note"])
        self.assertEqual(1, len(api.projects), "the old project went missing")

    def test_an_unverifiable_upload_deletes_nothing(self):
        """Something uploaded, but it is not in the listing.

        Deleting on the strength of "the call returned" would destroy the only
        remaining copy on the evidence of a call that may have gone nowhere.
        """
        mgr, api = self._mgr(appears=False)
        out = mgr.replace_cloud_project(str(self.esx), "old-1")
        self.assertIn("error", out)
        self.assertFalse(out.get("deletedOld"))
        self.assertEqual([], api.deleted)
        self.assertIn("left alone", out["error"])

    def test_a_failed_delete_says_there_are_two_and_which_is_new(self):
        """The failure he must not be left to discover on his own."""
        mgr, api = self._mgr(delete_raises=True)
        out = mgr.replace_cloud_project(str(self.esx), "old-1")
        self.assertFalse(out.get("ok"))
        self.assertFalse(out.get("deletedOld"))
        self.assertEqual("delete", out["step"])
        self.assertEqual("new-1", out["newId"])
        self.assertEqual("old-1", out["oldId"])
        self.assertIn("two projects", out["note"])
        self.assertIn("newer one is the good copy", out["note"])

    def test_it_uploads_into_the_site_the_old_one_was_in(self):
        mgr, api = self._mgr()
        seen = {}
        real = mgr.upload_project

        def watched(path, site_id=None, progress_cb=None):
            seen["site"] = site_id
            return real(path, site_id=site_id)

        mgr.upload_project = watched
        mgr.replace_cloud_project(str(self.esx), "old-1")
        self.assertEqual("site-9", seen.get("site"))

    def test_a_project_that_has_already_gone_is_reported_not_guessed(self):
        mgr, api = self._mgr()
        out = mgr.replace_cloud_project(str(self.esx), "not-there")
        self.assertIn("no longer there", out["error"])
        self.assertEqual([], api.deleted)

    def test_it_ends_with_one_project_under_the_expected_name(self):
        """The acceptance test, and the known duplicate mechanism.

        Ekahau names an upload from `project.json` inside the .esx and the
        uploader then renames to the local filename, so the failure mode is
        ending up with two things called almost the same. One, named right.
        """
        mgr, api = self._mgr()
        out = mgr.replace_cloud_project(str(self.esx), "old-1")
        self.assertTrue(out.get("ok"))
        names = [p["name"] for p in api.projects]
        self.assertEqual(1, len(names), names)
        self.assertEqual("Alpha Survey", names[0])


    def test_the_upload_really_does_happen_before_the_delete(self):
        """The order, asserted as an order rather than as an end state.

        Two tests here were assertions about the *docstring* - that it contains
        the words "inverted", "duplicate", "batch/update" and "S3". They were
        the A34 case in `docs/audits/cloud-manager-2026-09-18.md`, and the
        audit's charge was fair: rewording the prose failed the suite while the
        safety property itself went unchecked by them. Renaming `inverted` to
        `reversed` turned CI red with no behaviour change at all.

        The reasoning still belongs in the docstring, and it is still there.
        What it does not need is a test policing its vocabulary, so this holds
        the property those two gestured at instead.

        **And the property was genuinely unheld.** The test named
        `test_the_old_project_is_deleted_only_after_the_upload` asserts that a
        delete happened and that an upload happened - both true of a
        delete-then-upload implementation that succeeds. Only the failure-path
        tests would have caught the order, and by then the name of the test
        that should have caught it is pointing at the wrong thing.
        """
        mgr, api = self._mgr()
        out = mgr.replace_cloud_project(str(self.esx), "old-1")
        self.assertTrue(out.get("ok"), out)
        self.assertIn("upload", api.calls)
        self.assertIn("delete", api.calls)
        self.assertLess(api.calls.index("upload"), api.calls.index("delete"),
                        "the old project was deleted before the new one was "
                        "uploaded: %s" % api.calls)

    def test_nothing_is_deleted_until_the_upload_has_been_verified(self):
        """The project list is re-read between the two, and that is the check.

        Uploading and then deleting straight away would still be "upload
        first", and would still destroy the only remaining copy on the strength
        of a call that returned - which is exactly what
        `test_an_unverifiable_upload_deletes_nothing` refuses.
        """
        mgr, api = self._mgr()
        mgr.replace_cloud_project(str(self.esx), "old-1")
        after_upload = api.calls[api.calls.index("upload"):]
        self.assertIn("verify", after_upload,
                      "the project list was never re-read after the upload, so "
                      "nothing confirmed the new project exists: %s" % api.calls)
        self.assertLess(after_upload.index("verify"), after_upload.index("delete"),
                        "the delete came before the verification: %s" % api.calls)


class ItIsReachableAndHonestTests(unittest.TestCase):

    def test_the_page_can_call_it(self):
        import server
        self.assertIn("replace_cloud_project", server.CLOUD_ACTIONS)


if __name__ == "__main__":
    unittest.main()
