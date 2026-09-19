"""The project an upload claims to have created has to be the one it created.

`upload_project` could not ask Ekahau what it had just made - the commit
endpoint returns no project id - so it diffs the listing and looks for a row
that was not there before. That is sound. What it did with the answer was not:

    new_ones = [p for p in after if p["id"] not in before_ids]
    new_project = new_ones[0]

No name check, no "exactly one" rule. Four things then happened to whatever
that id named: it was renamed to his filename, filed into his site, downloaded
back **over his local .esx**, and - when the caller was
`replace_cloud_project` - his original cloud project was deleted on the
strength of it.

`_await_new_project` in this same file already states the rule, and states why:

    "a project that was not there a minute ago" is not good enough on an
    account other people also write to ... taking the first new row would
    eventually delete his old project on the strength of somebody else's new
    one.

That rule was only ever applied on the fallback path. This file drives the
primary one.

**The window is not small.** The diff is taken before a multi-megabyte upload
and read after it, so anything that appears in the shared account across that
whole span is a candidate - a colleague's upload, or a project shared in.

Only Ekahau's HTTP surface is faked, so the real listing poll, the real rename
and the real sync-back all run. Every name, address and site is invented.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tools import cloud_manager as cm

#: What Ekahau names the project, taken from `project.json` inside the .esx -
#: which is why the manager renames it to the filename afterwards, and why
#: both spellings have to count as expected.
INTERNAL_NAME = "Riverside Baseline"
FILE_STEM = "SITE1 Riverside Phase 3"


def _esx(path: Path, project_id: str = "local-uuid-1") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"project": {"id": project_id, "name": INTERNAL_NAME,
                       "history": {"createdBy": "survey.lead@example.invalid",
                                   "modifiedAt": "2026-09-19T00:00:00Z"}}}
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project.json", json.dumps(doc))
    return path


class _StubEkahau:
    """Ekahau, as far as this operation touches it.

    `foreign` is the part that matters: a project that appears in the listing
    during the upload window and is nothing to do with us. `foreign_only`
    holds our own upload back entirely, which is the shape of a slow commit
    on a busy account.
    """

    def __init__(self, *, foreign=None, foreign_only=False):
        self.projects = [{"id": "old-1", "name": FILE_STEM}]
        self.datasets = [{"id": "old-1", "siteId": "site-9"}]
        self.deleted: list[str] = []
        self.uploaded: list[str] = []
        self.renamed: list[tuple[str, str]] = []
        self.assigned: list[tuple[str, str]] = []
        self.downloaded: list[str] = []
        self.reads = 0
        self._pending = None
        self._foreign = foreign
        self._foreign_only = foreign_only

    def get_projects(self):
        #: The first read is the "before" snapshot the diff is taken against,
        #: so anything injected into it is not new and proves nothing. The
        #: colleague's upload lands *after* it - which is the whole window
        #: this is about, and it is as long as his own upload takes.
        self.reads += 1
        if self._foreign is not None and self.reads > 1:
            self.projects.append(self._foreign)
            self._foreign = None
        if self._pending and not self._foreign_only:
            self.projects.append(self._pending)
            self._pending = None
        return [dict(p) for p in self.projects]

    def get_dataset_listing(self):
        return [dict(d) for d in self.datasets]

    def upload_project(self, esx_path, progress_cb=None):
        self.uploaded.append(str(esx_path))
        self._pending = {"id": "new-1", "name": INTERNAL_NAME}
        return {"ok": True, "status": 200}

    def download_project(self, pid, progress_cb=None):
        self.downloaded.append(pid)
        return {"esx": b"PK\x05\x06" + b"\0" * 18, "name": "whatever"}

    def rename_project(self, pid, name):
        self.renamed.append((pid, name))
        for p in self.projects:
            if p["id"] == pid:
                p["name"] = name
        return {"ok": True}

    def assign_to_site(self, site_id, dataset_id, dtype=None):
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
        self.esx = _esx(self.root / "SITE1 Riverside" / (FILE_STEM + ".esx"))
        self.original = self.esx.read_bytes()
        patch = mock.patch.object(cm.time, "sleep", lambda *_a, **_k: None)
        patch.start()
        self.addCleanup(patch.stop)

    def _mgr(self, **kw):
        api = _StubEkahau(**kw)
        return _Manager(api, self.root), api


class SomebodyElsesProjectIsNeverMistakenForOurs(_Base):
    """A colleague uploads to the shared account while his upload is running."""

    COLLEAGUE = {"id": "their-7", "name": "Northgate Depot Walkthrough"}

    def test_a_foreign_project_is_not_adopted_as_the_upload(self):
        mgr, api = self._mgr(foreign=dict(self.COLLEAGUE), foreign_only=True)
        out = mgr.upload_project(str(self.esx), "site-9")

        self.assertNotEqual("their-7", out.get("datasetId"),
                            "a colleague's project was adopted as the upload")
        self.assertIsNone(out.get("datasetId"),
                          "nothing should have been identified: " + repr(out))

    def test_a_foreign_project_is_never_renamed_to_his_filename(self):
        mgr, api = self._mgr(foreign=dict(self.COLLEAGUE), foreign_only=True)
        mgr.upload_project(str(self.esx), "site-9")
        self.assertEqual([], api.renamed,
                         "a project that is not ours was renamed: %r" % (api.renamed,))

    def test_a_foreign_project_is_never_filed_into_his_site(self):
        mgr, api = self._mgr(foreign=dict(self.COLLEAGUE), foreign_only=True)
        mgr.upload_project(str(self.esx), "site-9")
        self.assertEqual([], api.assigned,
                         "a project that is not ours was assigned: %r" % (api.assigned,))

    def test_his_local_file_is_not_overwritten_with_it(self):
        """The sync-back writes the cloud copy over the local .esx. There is no
        copy kept anywhere, so the local file is the only one there is."""
        mgr, api = self._mgr(foreign=dict(self.COLLEAGUE), foreign_only=True)
        mgr.upload_project(str(self.esx), "site-9")
        self.assertEqual([], api.downloaded,
                         "an unidentified project was downloaded over his file")
        self.assertEqual(self.original, self.esx.read_bytes(),
                         "the local .esx was overwritten")

    def test_the_replace_deletes_nothing_on_the_strength_of_it(self):
        """The end of the chain, and the part that cannot be undone."""
        mgr, api = self._mgr(foreign=dict(self.COLLEAGUE), foreign_only=True)
        out = mgr.replace_cloud_project(str(self.esx), "old-1")

        self.assertEqual([], api.deleted,
                         "the old cloud project was deleted: %r" % (api.deleted,))
        self.assertFalse(out.get("deletedOld"))
        self.assertTrue(out.get("error"), "the refusal was not reported: " + repr(out))

    def test_two_new_projects_at_once_is_refused_rather_than_guessed(self):
        """Ours *and* theirs both land before the listing is read."""
        mgr, api = self._mgr(foreign=dict(self.COLLEAGUE))
        out = mgr.upload_project(str(self.esx), "site-9")
        self.assertIsNone(out.get("datasetId"),
                          "one of two new projects was picked: " + repr(out))
        self.assertEqual([], api.renamed)
        self.assertEqual([], api.assigned)


class TheOrdinaryUploadStillWorks(_Base):
    """Refusing is only correct if it refuses the right thing."""

    def test_the_only_new_project_is_identified_and_finished(self):
        mgr, api = self._mgr()
        out = mgr.upload_project(str(self.esx), "site-9")

        self.assertEqual("new-1", out.get("datasetId"), out)
        self.assertTrue(out.get("ok"), out)
        # Ekahau named it from inside the file; it is renamed to the filename.
        self.assertEqual([("new-1", FILE_STEM)], api.renamed)
        self.assertEqual([("site-9", "new-1")], api.assigned)
        self.assertEqual(["new-1"], api.downloaded)

    def test_the_replace_still_completes(self):
        mgr, api = self._mgr()
        out = mgr.replace_cloud_project(str(self.esx), "old-1")
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(["old-1"], api.deleted)
        self.assertEqual(1, len(api.projects), api.projects)


if __name__ == "__main__":
    unittest.main()
