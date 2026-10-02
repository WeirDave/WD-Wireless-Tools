"""The update check answers "could not check" when GitHub names no release.

`/api/update/status` indexed whatever `fetch_latest_release` returned as a
release, so a None - or a body that was not a release at all - came back as a
500 and the About panel showed a failure instead of the "could not check"
line it already has. Both routes are held: the ZIP install, which asks the API
for the release itself, and the git install, which only wants the notes and
must still answer from git.

GitHub is never contacted: the lookup and the install are stubbed.
"""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from tools import updater  # noqa: E402

ZIP_INSTALL = {"isGitInstall": False, "currentVersion": "2.5.0", "method": "zip",
               "releasesUrl": "https://github.com/o/r/releases"}
GIT_INSTALL = {"isGitInstall": True, "currentVersion": "2.5.0", "method": "git",
               "releasesUrl": "https://github.com/o/r/releases"}


class _Resp:
    status_code = 200
    ok = True
    headers = {}

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class NoReleaseIsCouldNotCheck(unittest.TestCase):
    def setUp(self):
        self.client = server.app.test_client()
        for p in (mock.patch.object(updater, "remote_branch_state", return_value=None),
                  mock.patch.object(updater, "remote_release_tag", return_value="v2.9.0")):
            p.start()
            self.addCleanup(p.stop)

    def status(self, install, release):
        with mock.patch.object(updater, "detect_install", return_value=install), \
             mock.patch.object(updater, "fetch_latest_release", return_value=release):
            r = self.client.get("/api/update/status")
        return r.status_code, json.loads(r.data)

    def test_a_zip_install_with_no_release_says_it_could_not_check(self):
        code, out = self.status(ZIP_INSTALL, None)
        self.assertEqual(code, 200, out)
        self.assertIsNone(out["latest"])
        self.assertFalse(out["updateAvailable"])
        self.assertTrue(out.get("latestError"), "the page's could-not-check line has its reason")

    def test_a_git_install_still_answers_from_git(self):
        code, out = self.status(GIT_INSTALL, None)
        self.assertEqual(code, 200, out)
        self.assertEqual(out["latest"]["version"], "2.9.0")
        self.assertTrue(out["updateAvailable"])
        self.assertIn("notesError", out)

    def test_a_release_with_no_tag_is_no_release(self):
        code, out = self.status(ZIP_INSTALL, {"notes": "x"})
        self.assertEqual(code, 200, out)
        self.assertTrue(out.get("latestError"))


class AnEmptyAnswerFromGitHubIsAnUpdateError(unittest.TestCase):
    """The lookup itself: a body that is not a release is "could not check",
    not an AttributeError."""

    def setUp(self):
        self.reset()
        self.addCleanup(self.reset)

    @staticmethod
    def reset():
        updater._RELEASE_CACHE.update(
            {"at": 0.0, "data": None, "etag": None, "blocked_until": 0.0})

    def test_null_and_lists_and_unreadable_bodies(self):
        for body in (None, ["v9.9.9"], ValueError("not json")):
            with self.subTest(body=repr(body)):
                self.reset()
                with mock.patch("requests.get", lambda *a, **k: _Resp(body)):
                    with self.assertRaises(updater.UpdateError):
                        updater.fetch_latest_release()


if __name__ == "__main__":
    unittest.main()
