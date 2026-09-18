"""Downloading the cloud copy over a local .esx.

This is the one operation in Cloud Manager that destroys someone's work, so
what is checked here is mostly what it must NOT do: never overwrite when the
local copy is the newer one, never leave a half-written file, and never
proceed without keeping the copy it is about to replace.
"""
from __future__ import annotations

import json
import os
import sys
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import cloud_manager as cm  # noqa: E402


def _esx(path: Path, name: str, modified_iso: str) -> None:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project.json", json.dumps({"project": {
            "id": "proj-1", "name": name, "title": name,
            "history": {"modifiedAt": modified_iso},
        }}))
        z.writestr("accessPoints.json", json.dumps({"accessPoints": []}))
        z.writestr("floorPlans.json", json.dumps({"floorPlans": []}))


class _Resp:
    def __init__(self, code, payload=None):
        self.status_code = code
        self._payload = payload or {}

    def json(self):
        return self._payload


class _StubApi:
    def __init__(self, get_result, download_result=None):
        self._get = get_result
        self._download = download_result

    def get(self, url):
        if isinstance(self._get, Exception):
            raise self._get
        return self._get

    def download_project(self, project_id, progress_cb=None):
        if isinstance(self._download, Exception):
            raise self._download
        return self._download


CLOUD_NEW = "2026-09-04T08:00:00.000Z"
LOCAL_OLD = "2026-08-01T08:00:00.000Z"


class CloudPullTests(unittest.TestCase):
    def setUp(self):
        # `addCleanup`, not a bare mkdtemp. Without it this leaked one
        # directory per test method: 1,314 of them were on his machine when
        # the housekeeping action first counted, from this line alone.
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-cloud-pull-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.local = self.tmp / "Example St - PD.esx"
        _esx(self.local, "Example St - PD", LOCAL_OLD)
        self.original = self.local.read_bytes()

        buf = self.tmp / "_cloud.esx"
        _esx(buf, "Example St - PD", CLOUD_NEW)
        self.cloud_bytes = buf.read_bytes()
        buf.unlink()

    def _run(self, *, get=None, download=None):
        mgr = cm.CloudManager.__new__(cm.CloudManager)
        mgr.config = {"output_dir": str(self.tmp)}
        mgr._ensure = lambda: True
        mgr.api = _StubApi(
            get if get is not None else _Resp(200, {"name": "Example St - PD",
                                                    "modifiedAt": CLOUD_NEW}),
            download if download is not None else {"esx": self.cloud_bytes},
        )
        return mgr.verify_replace_local("cloud-proj", str(self.local))

    def _backups(self):
        """Anywhere under the project folder.

        The copy used to sit beside the live file; it now lands in
        `<project folder>/backups/`, out of the working folder and out of
        Cloud Manager's scan. Searching recursively keeps this test about
        *whether* a backup was kept rather than about where it went.
        """
        return sorted(self.tmp.rglob("*.previous-*"))

    def assertLocalUntouched(self):
        self.assertTrue(self.local.exists(), "the local file was removed")
        self.assertEqual(self.local.read_bytes(), self.original,
                         "the local file was modified on a path that should not touch it")
        self.assertEqual(self._backups(), [], "a backup was left behind by a failed run")
        self.assertEqual(list(self.tmp.glob("*.tmp")), [], "a temp file was left behind")

    # ---- the working path --------------------------------------------------

    def test_cloud_newer_replaces_and_keeps_the_previous_copy(self):
        res = self._run()
        self.assertTrue(res.get("ok"), res)
        self.assertNotEqual(self.local.read_bytes(), self.original)

        backups = self._backups()
        self.assertEqual(len(backups), 1, "expected exactly one .previous- copy")
        self.assertEqual(backups[0].read_bytes(), self.original,
                         "the backup is not the file that was replaced")
        self.assertEqual(backups[0].suffix, ".esx",
                         "the backup should still open as a project")
        from tools import cloud_manager as _cm
        self.assertIn(_cm.BACKUP_DIR_NAME, backups[0].parts,
                      "the backup is still sitting beside the live project")
        self.assertEqual(res.get("backup"), str(backups[0]))
        self.assertEqual(list(self.tmp.glob("*.tmp")), [])

    def test_result_carries_both_edit_times_for_the_confirm(self):
        res = self._run()
        self.assertTrue(res.get("ok"))
        self.assertGreater(res["cloudMtime"], res["localMtime"],
                           "the cloud copy should be the newer one here")

    # ---- everything that must not overwrite --------------------------------

    def test_local_newer_is_refused(self):
        _esx(self.local, "Example St - PD", "2026-10-01T08:00:00.000Z")
        self.original = self.local.read_bytes()
        res = self._run()
        self.assertEqual(res.get("error"), "local_newer")
        self.assertLocalUntouched()

    def test_deleted_cloud_project_says_so(self):
        res = self._run(get=_Resp(404))
        self.assertIn("no longer in Ekahau Cloud", res.get("error", ""))
        self.assertLocalUntouched()

    def test_expired_sign_in_says_so(self):
        res = self._run(get=_Resp(401))
        self.assertIn("sign-in has expired", res.get("error", ""))
        self.assertLocalUntouched()

    def test_no_network_on_lookup(self):
        res = self._run(get=OSError("getaddrinfo failed"))
        self.assertIn("Could not reach Ekahau Cloud", res.get("error", ""))
        self.assertLocalUntouched()

    def test_network_dies_mid_download(self):
        res = self._run(download=OSError("connection reset"))
        self.assertIn("Nothing was changed locally", res.get("error", ""))
        self.assertLocalUntouched()

    def test_download_error_payload_is_passed_through(self):
        res = self._run(download={"error": "Project export failed on the server"})
        self.assertIn("export failed", res.get("error", ""))
        self.assertLocalUntouched()

    def test_path_outside_the_configured_folder_is_refused(self):
        _outside_dir = Path(tempfile.mkdtemp(prefix="wd-cloud-outside-"))
        self.addCleanup(shutil.rmtree, _outside_dir, True)
        outside = _outside_dir / "elsewhere.esx"
        _esx(outside, "Elsewhere", LOCAL_OLD)
        mgr = cm.CloudManager.__new__(cm.CloudManager)
        mgr.config = {"output_dir": str(self.tmp)}
        mgr._ensure = lambda: True
        mgr.api = _StubApi(_Resp(200, {"modifiedAt": CLOUD_NEW}), {"esx": self.cloud_bytes})
        res = mgr.verify_replace_local("cloud-proj", str(outside))
        self.assertIn("outside the configured folder", res.get("error", ""))
        self.assertEqual(list(outside.parent.glob("*.previous-*")), [])


class CloudPullWiringTests(unittest.TestCase):
    """The badge is the control now, so the gate has to stay where it is."""

    def setUp(self):
        self.js = (ROOT / "web" / "assets" / "js" / "cloud.js").read_text(encoding="utf-8")

    def test_only_proven_pairings_can_be_overwritten(self):
        self.assertIn("const PULLABLE_MATCH_TYPES = new Set(['id', 'manual', 'exact'])", self.js,
                      "a code or fuzzy match is a guess at the name - overwriting on it "
                      "can destroy a different project")

    def test_the_cloud_newer_badge_is_wired_to_the_action(self):
        # It reported a state and offered nothing to do about it for a long time.
        start = self.js.index("function stalenessBadgeHtml(")
        body = self.js[start:self.js.index("\n}", start)]
        self.assertIn("verifyReplaceLocal(", body)
        # `is-action` was the class that distinguished a clickable pill from a
        # decorative one, back when both were pills. Everything in the band is
        # a button now, so the property is that this one is pressable and
        # wired - not that it carries a class telling the stylesheet so.
        i = body.index("verifyReplaceLocal(")
        self.assertIn("<button", body[:i])
        self.assertIn("onclick=", body[:i])

    def test_pushing_up_needs_a_stronger_pairing_than_pulling_down(self):
        """This used to assert that nothing could push a local file up, which
        was true until the row was wired to `replace_cloud_project`.

        What replaces it is the rule that actually matters: the two directions
        are not equally recoverable. A pull keeps the file it replaced in
        `backups/<site>/`, so it is offered even on a bare name match. A push
        deletes the old cloud project, and a cloud delete does not come back -
        so it requires Ekahau's own id, or a pairing he made himself.
        """
        self.assertIn(
            "const PUSHABLE_MATCH_TYPES = new Set(['id', 'manual', 'exact'])",
            self.js,
            "replacing a cloud project on a *guessed* pairing would delete a "
            "project that was never the counterpart - but a shared name is not "
            "a guess, and excluding it made the control unusable for the case "
            "he actually has")
        self.assertIn("const PROVEN_MATCH_TYPES = new Set(['id', 'manual'])",
                      self.js,
                      "a name-only pair is allowed and asks first; the proven "
                      "ones go straight through")
        start = self.js.index("function stalenessBadgeHtml(")
        body = self.js[start:self.js.index(chr(10) + "}", start)]
        local_part = body[body.index("local_newer"):]
        self.assertIn("canPushToCloud(r)", local_part)
        self.assertIn("pushLocalOverCloud(", local_part)

if __name__ == "__main__":
    unittest.main()
