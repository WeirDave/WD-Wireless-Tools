"""The replace has to read the key the upload actually writes.

First real-account run of Local -> Cloud replace, and it stopped dead:

    "It says the upload finished but the new project could not be identified,
    so nothing was deleted."

The upload worked. The safety ordering worked - nothing was deleted, which is
the whole point of uploading before removing. What failed was one line:

    new_id = up.get("id") or up.get("projectId")

`upload_project` returns the new project under **`datasetId`**, on every one of
its success paths, and has done since it was written. So `new_id` was always
empty, and the replace bailed **before** verification ever ran. Not a race, not
the stale internal project name, not the owner filter - two functions in one
file disagreeing about one key, failing 100% of the time for everybody.

**Why the existing tests were green while it was broken for everybody.**
`tests/test_cloud_replace_project.py` replaces `mgr.upload_project` with

    def fake_upload(...): return {"ok": True, "id": "new-1"}

and `{"ok": True, "id": ...}` is a shape the real function does not return.
The stub invented the contract instead of copying it, so the test proved the
composition around a function that does not exist. That is the same defect
class as asserting a source file contains `doTheThing(`: it was never going to
fail on this.

So this file stubs **Ekahau** and nothing else. `replace_cloud_project` calls
the real `upload_project`, which does its real listing poll, its real rename
and its real sync-back. Only the HTTP boundary is fake. Every name invented;
Ekahau is never contacted.
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


def _esx(path: Path, project_id: str = "local-uuid-1") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"project": {"id": project_id, "name": "Stale Internal Name",
                       "history": {"createdBy": "survey.lead@example.invalid",
                                   "modifiedAt": "2026-09-18T00:00:00Z"}}}
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project.json", json.dumps(doc))
    return path


class _StubEkahau:
    """Ekahau's HTTP surface, as far as this operation touches it.

    `upload_project` returns what the real one returns: whatever the commit
    endpoint said, which carries **no project id**. That is why the manager
    has to find the new project by diffing the listing, and why the key it
    publishes it under is the only way anything downstream can know it.

    `listing_lag` holds the new project back for that many reads of
    `get_projects`, which is the shape of an eventually-consistent listing.
    """

    def __init__(self, *, listing_lag: int = 0, never_appears: bool = False):
        self.projects = [{"id": "old-1", "name": "Riverside Block - Phase 3"}]
        self.datasets = [{"id": "old-1", "siteId": "site-9"}]
        self.deleted: list[str] = []
        self.uploaded: list[str] = []
        self.renamed: list[tuple[str, str]] = []
        self.assigned: list[tuple[str, str]] = []
        self.reads = 0
        self._pending = None
        self._lag = listing_lag
        self._never = never_appears

    # -- reads ---------------------------------------------------------
    def get_projects(self):
        self.reads += 1
        if self._pending and not self._never:
            if self._lag <= 0:
                self.projects.append(self._pending)
                self._pending = None
            else:
                self._lag -= 1
        return [dict(p) for p in self.projects]

    def get_dataset_listing(self):
        return [dict(d) for d in self.datasets]

    # -- writes --------------------------------------------------------
    def upload_project(self, esx_path, progress_cb=None):
        self.uploaded.append(str(esx_path))
        # Ekahau names the new project from `project.json` inside the .esx,
        # not from the filename - which is why the manager renames afterwards.
        self._pending = {"id": "new-1", "name": "Stale Internal Name"}
        return {"ok": True, "status": 200}

    def download_project(self, pid, progress_cb=None):
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
        self.esx = _esx(self.root / "Riverside Block" / "Riverside Block - Phase 3.esx")
        # The real poll sleeps; the question here is what the code decides,
        # not how long it waits for it.
        patch = mock.patch.object(cm.time, "sleep", lambda *_a, **_k: None)
        patch.start()
        self.addCleanup(patch.stop)

    def _mgr(self, **kw):
        api = _StubEkahau(**kw)
        return _Manager(api, self.root), api


class TheReplaceRunsEndToEndTests(_Base):
    """Nothing between `replace_cloud_project` and Ekahau is faked."""

    def test_the_old_project_is_deleted_after_a_real_upload(self):
        """The bug, stated as the thing he tried to do.

        This is the assertion the shipped code fails: it reported that the
        new project could not be identified and left both copies in place.
        """
        mgr, api = self._mgr()
        out = mgr.replace_cloud_project(str(self.esx), "old-1")

        self.assertTrue(out.get("ok"), out)
        self.assertEqual(["old-1"], api.deleted,
                         "the old cloud project was not removed")
        self.assertEqual(1, len(api.uploaded), "the local file was not uploaded")
        self.assertTrue(out.get("deletedOld"))
        self.assertEqual("new-1", out.get("newId"))

    def test_exactly_one_project_is_left_behind(self):
        """The duplicate is the thing he has been burned by. Count them."""
        mgr, api = self._mgr()
        mgr.replace_cloud_project(str(self.esx), "old-1")
        self.assertEqual(1, len(api.projects),
                         f"expected one project, found: {api.projects}")
        self.assertEqual("new-1", api.projects[0]["id"])

    def test_the_new_project_carries_the_local_filename(self):
        """Ekahau names an upload from the .esx's internal name, which on his
        files is stale. The rename is what makes the cloud say what he called
        the file, and the replace has to report that name."""
        mgr, api = self._mgr()
        out = mgr.replace_cloud_project(str(self.esx), "old-1")
        self.assertIn(("new-1", "Riverside Block - Phase 3"), api.renamed)
        self.assertEqual("Riverside Block - Phase 3", out.get("name"))


class TheSharesGoWithTheOldProjectTests(_Base):
    """A successful replace has a consequence he did not ask for.

    A share is keyed to the project id, and this operation creates a new
    project rather than editing the old one, so everyone the old copy was
    shared with loses access the moment the replace succeeds. Nothing
    re-applies them - sharing other people's access on his behalf is not a
    side effect an upload gets to have - so the result says who, by name, at
    the moment it happens rather than when somebody asks why they cannot open
    it. Every address here is invented at a documentation domain.
    """

    def test_a_successful_replace_reports_the_shares_it_dropped(self):
        mgr, api = self._mgr()
        api.projects[0]["sharedWith"] = ["colleague.one@example.invalid",
                                         "colleague.two@example.invalid"]
        out = mgr.replace_cloud_project(str(self.esx), "old-1")

        self.assertTrue(out.get("ok"), out)
        self.assertEqual(["colleague.one@example.invalid",
                          "colleague.two@example.invalid"],
                         out.get("lostShares"))
        note = out.get("note") or ""
        self.assertIn("colleague.one@example.invalid", note)
        self.assertIn("re-share", note.lower())

    def test_an_unshared_project_says_nothing_extra(self):
        """The note has to mean something when it appears."""
        mgr, _api = self._mgr()
        out = mgr.replace_cloud_project(str(self.esx), "old-1")
        self.assertTrue(out.get("ok"), out)
        self.assertIsNone(out.get("note"))
        self.assertIsNone(out.get("lostShares"))


class TheKeyContractTests(_Base):
    """The specific disagreement, pinned so it cannot drift back.

    A test that reads the key name out of the source would pass with the
    feature deleted. This runs the real `upload_project` and asks whether the
    real extraction in `replace_cloud_project` can find what it published.
    """

    def test_whatever_key_the_upload_publishes_the_replace_reads(self):
        mgr, api = self._mgr()
        up = mgr.upload_project(str(self.esx), site_id="site-9")

        self.assertFalse(up.get("error"), up)
        keys_with_the_id = {k for k, v in up.items() if v == "new-1"}
        self.assertTrue(keys_with_the_id,
                        f"the upload published no id at all: {up}")

        # The same expression `replace_cloud_project` uses.
        found = up.get("datasetId") or up.get("id") or up.get("projectId") or ""
        self.assertEqual(
            "new-1", found,
            f"upload_project returns the new id under {sorted(keys_with_the_id)}, "
            f"which replace_cloud_project does not read",
        )

    def test_the_ordinary_replace_never_falls_back_to_finding_it(self):
        """The check that actually fails when the keys drift apart.

        There is a fallback - diff the listing and identify the new project
        from the id inside the local file - and it is deliberately narrow,
        because the next step deletes something. It exists for a listing that
        has not caught up, not for everyday use: leaning on it on every
        replace would mean the tool routinely decides what to delete by
        inference when the upload could simply have told it.

        So the happy path must never reach it. With the key mismatch in place
        it reached it every single time, which is how a 100%-reproducible
        defect could hide behind a passing suite.

        **`upload_project` calls it too now, and that is not this.** The
        upload identifies what it created on evidence rather than taking the
        first new row in the listing, so one call from inside the upload is
        correct and expected. What must not happen is a call *after* the
        upload has returned - that one is the replace deciding for itself
        which project to delete. So the order is asserted, not the count.
        """
        mgr, api = self._mgr()
        events = []
        real_await = mgr._await_new_project
        real_upload = mgr.upload_project

        def spy_await(*a, **k):
            events.append("await")
            return real_await(*a, **k)

        def spy_upload(*a, **k):
            events.append("upload:start")
            try:
                return real_upload(*a, **k)
            finally:
                events.append("upload:end")

        mgr._await_new_project = spy_await
        mgr.upload_project = spy_upload

        out = mgr.replace_cloud_project(str(self.esx), "old-1")

        self.assertTrue(out.get("ok"), out)
        self.assertIn("upload:end", events, events)
        after_upload = events[events.index("upload:end"):]
        self.assertNotIn(
            "await", after_upload,
            "the replace had to go looking for the project the upload just "
            "made - the upload's return key and the replace's lookup disagree",
        )


class TheListingIsAskedMoreThanOnceTests(_Base):
    """A listing that has not caught up and an upload that failed read the
    same on one look, and they have opposite consequences: refusing to delete
    leaves him with the duplicate the refusal was protecting him from."""

    def test_verification_waits_for_a_lagging_listing(self):
        mgr, api = self._mgr(listing_lag=3)
        out = mgr.replace_cloud_project(str(self.esx), "old-1")
        self.assertTrue(out.get("ok"), out)
        self.assertEqual(["old-1"], api.deleted)

    def test_verify_uploaded_asks_again_before_giving_up(self):
        mgr, api = self._mgr()
        api._pending = {"id": "new-1", "name": "x"}
        api._lag = 3
        self.assertTrue(mgr._verify_uploaded("new-1", str(self.esx)).get("ok"))
        self.assertGreater(api.reads, 1, "it gave up on the first read")

    def test_the_fallback_refuses_when_it_cannot_tell_which_one_is_ours(self):
        """The fallback decides what gets deleted, so it does not guess.

        Two projects appeared while the upload was running - a large file is a
        long window and other people write to this account. "the one that was
        not there before" is two rows here, and neither the local file's id
        nor an expected name picks one out. Refusing leaves him a duplicate to
        tidy; guessing would delete a project on the strength of somebody
        else's upload.
        """
        mgr, api = self._mgr()
        api.projects.append({"id": "somebody-else", "name": "Not Mine"})
        api.projects.append({"id": "also-new", "name": "Nor This"})
        got = mgr._await_new_project({"old-1"}, str(self.esx),
                                     expect_names=("Riverside Block - Phase 3",))
        self.assertEqual({}, got, f"it picked one anyway: {got}")

    def test_the_fallback_identifies_ours_by_the_id_inside_the_file(self):
        """Positive identification, not elimination. The sync-back has already
        put the new cloud project's id inside the local .esx, so even with
        other new projects alongside it, the right one is knowable."""
        mgr, api = self._mgr()
        _esx(self.esx, project_id="NEW-1")  # as the sync-back leaves it
        api.projects.append({"id": "somebody-else", "name": "Not Mine"})
        api.projects.append({"id": "new-1", "name": "Riverside Block - Phase 3"})
        got = mgr._await_new_project({"old-1"}, str(self.esx))
        self.assertEqual("new-1", got.get("id"), got)
        self.assertIn("id inside the local file", got.get("how", ""))

    def test_it_still_gives_up_when_the_project_really_is_absent(self):
        """Retrying must not become 'delete the old one anyway'."""
        mgr, api = self._mgr()
        out = mgr._verify_uploaded("never-uploaded", str(self.esx))
        self.assertFalse(out.get("ok"))
        self.assertEqual([], api.deleted)


class ItSaysWhatItUploadedTests(_Base):
    """"the new project could not be identified" is the one report he cannot
    act on. If the tool cannot name it, it still knows what it sent and what
    name it would have landed under - so it says both, and says there are two
    copies."""

    def test_an_unconfirmable_upload_names_the_project_and_the_duplicate(self):
        mgr, api = self._mgr(never_appears=True)
        out = mgr.replace_cloud_project(str(self.esx), "old-1")

        self.assertFalse(out.get("ok"))
        self.assertFalse(out.get("deletedOld"))
        self.assertEqual([], api.deleted, "it deleted without confirming")

        self.assertEqual("Riverside Block - Phase 3", out.get("uploadedAs"))
        note = out.get("note") or ""
        self.assertIn("Riverside Block - Phase 3", note,
                      f"the report does not name what it uploaded: {out}")
        self.assertIn("two copies", note.lower(),
                      f"the report does not say a duplicate exists: {out}")

    def test_a_failed_upload_still_says_nothing_was_deleted(self):
        """The other side of it: no upload, no duplicate, and say so."""
        mgr, api = self._mgr()
        api.upload_project = lambda *a, **k: {"error": "network went away"}
        out = mgr.replace_cloud_project(str(self.esx), "old-1")
        self.assertFalse(out.get("deletedOld"))
        self.assertEqual([], api.deleted)
        self.assertIn("nothing was deleted", (out.get("note") or "").lower())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
