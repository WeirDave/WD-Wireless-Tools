"""Two things the tool was saying that were not true.

**"a lot of extra backslashes."** The long-path fix shipped in v2.136.1 retries a
failed copy with the `\\?\` form, and when *that* failed too the exception it
raised named the prefixed path. `OSError.__str__` appends its filename through
`repr`, so every backslash was doubled before it reached the screen, and the
prefix's own two became four:

    [Errno 2] The system cannot find the path specified:
    '\\\\?\\C:\\Users\\...\\backups\\...'

An internal path form, escaped twice, in a notification, on top of a
265-character string nobody can read there. Two faults: the prefix escaping, and
`str(exc)` being used for a message at all.

**"you can't have other people's site names inside of your Ekahau."** The
External chip's tooltip ended "On the Sites tab this can be the site itself, not
only the projects in it." That is false twice over. Ekahau shares *projects*, not
sites, so a site in your account is yours. And the code cannot produce it either:
`build_sites_data` never puts an `owner` on a cloud site or on a local folder, so
`_isExternal` reads '' on both sides of a site row and can only ever return
false. A site appears under External because a project *inside* it does.
"""
from __future__ import annotations

import errno
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CLOUD_JS = ROOT / "web" / "assets" / "js" / "cloud.js"
CLOUD_HTML = ROOT / "web" / "cloud.html"
CLOUD_PY = ROOT / "tools" / "cloud_manager.py"

from tools import longpath as L


class NoPathIsEscapedIntoAMessage(unittest.TestCase):
    """What a person reads has no `repr` in it, and no `\\?\` either."""

    def _failure_message(self, dest, prefixed=False):
        exc = OSError(errno.ENOENT, "The system cannot find the path specified",
                      L.long_path(dest) if prefixed else str(dest))
        return L.describe_failure(exc, dest)

    def test_a_message_never_carries_a_doubled_backslash(self):
        dest = "C:\\Users\\someone\\Projects\\" + ("P" * 200) + ".esx"
        for prefixed in (False, True):
            msg = self._failure_message(dest, prefixed)
            self.assertNotIn("\\\\", msg,
                             f"doubled backslash reached the message: {msg}")

    def test_a_message_never_carries_the_internal_path_form(self):
        dest = "C:\\Users\\someone\\Projects\\" + ("P" * 200) + ".esx"
        msg = self._failure_message(dest, prefixed=True)
        self.assertNotIn("?\\", msg, "the \\\\?\\ prefix leaked into the message")

    def test_a_message_never_carries_the_path_at_all(self):
        """265 characters of path in a notification is not information. The
        full path goes to the log, where it can be read and copied."""
        dest = "C:\\Users\\someone\\Projects\\" + ("P" * 200) + ".esx"
        msg = self._failure_message(dest)
        self.assertNotIn("PPPP", msg)
        self.assertNotIn("C:\\", msg)

    def test_it_still_says_why(self):
        """Stripping the path must not strip the explanation with it."""
        dest = "C:\\a\\" + ("P" * 280) + ".esx"
        self.assertIn("The system cannot find the path specified",
                      self._failure_message(dest))

    @unittest.skipUnless(os.name == "nt", "260 is a Windows limit")
    def test_and_on_windows_says_what_to_do_about_the_length(self):
        """The length advice is Windows-only on purpose: POSIX has no such
        limit, and telling a Mac user to shorten a path would be noise."""
        dest = "C:\\a\\" + ("P" * 280) + ".esx"
        msg = self._failure_message(dest)
        self.assertIn(str(len(dest)), msg)
        self.assertIn(str(L.MAX_PATH), msg)
        self.assertRegex(msg, r"shorten|nearer the top")

    def test_a_short_path_gets_the_reason_without_the_length_lecture(self):
        msg = L.describe_failure(OSError(13, "Permission denied"), "C:\\a.esx")
        self.assertIn("Permission denied", msg)
        self.assertNotIn(str(L.MAX_PATH), msg)


class TheEndToEndMessageIsReadable(unittest.TestCase):
    """The whole sentence, as `set_internal_project_name` would return it.

    The failure is staged on the temp file the rewrite writes, because that is
    the path that fails in real life: it is the .esx path plus 14 characters,
    so on the longest-named projects it is the first thing in the operation to
    cross `MAX_PATH` even when the .esx itself did not.
    """

    def test_a_failed_write_produces_no_escaped_path(self):
        from tools import cloud_manager as cm
        import zipfile

        base = Path(tempfile.mkdtemp(prefix="wd-msg-"))
        self.addCleanup(shutil.rmtree, base, True)
        site = "ABCD1 - AB-99 - 100 Example Road, Anytown, Example State 0000"
        root = base / "Docs" / "Projects"
        (root / site).mkdir(parents=True)
        src = root / site / (site + " - Power Level Adjustment.esx")
        with zipfile.ZipFile(src, "w") as z:
            z.writestr("project.json", json.dumps({"project": {"name": "Old"}}))

        real = zipfile.ZipFile
        self.addCleanup(setattr, zipfile, "ZipFile", real)

        def fail_on_write(path, mode="r", *a, **kw):
            if mode == "w":
                raise OSError(errno.ENOENT,
                              "The system cannot find the path specified",
                              str(path))
            return real(path, mode, *a, **kw)

        zipfile.ZipFile = fail_on_write
        out = cm._rewrite_project_json(
            src, lambda proj, doc: (proj.__setitem__("name", "New"), True)[1])

        msg = out.get("error", "")
        self.assertTrue(msg, "the failure produced no message at all")
        self.assertNotIn("\\\\", msg, f"doubled backslash on screen: {msg}")
        self.assertNotIn("?\\", msg, f"the internal path form on screen: {msg}")
        self.assertIn("The system cannot find the path specified", msg)
        self.assertIn("the file is untouched", msg)

        # And it really is untouched.
        zipfile.ZipFile = real
        with real(src) as z:
            self.assertEqual("Old",
                             json.loads(z.read("project.json"))["project"]["name"])


class ASiteIsNeverSomebodyElses(unittest.TestCase):
    """Ekahau shares projects, not sites - and the code agrees."""

    def test_no_site_or_folder_is_given_an_owner_to_be_external_by(self):
        """Established by reading what `build_sites_data` builds, run rather
        than grepped: a site row's cloud half and local half both arrive
        without an `owner`, so `_isExternal` has nothing to compare."""
        import tools.cloud_manager as cm

        class FakeApi:
            def get_sites(self):
                return [{"id": "s1", "name": "Example Ridge"}]

            def get_dataset_listing(self):
                return [{"id": "d1", "siteId": "s1", "siteName": "Example Ridge",
                         "type": "SURVEY", "datasetUsers": [
                             {"username": "them@example.com", "role": "OWNER"},
                             {"username": "me@example.com", "role": "VIEWER"}]}]

            def get_projects(self):
                return [{"id": "d1", "name": "Example Ridge AP01",
                         "statistics": {"size": 10},
                         "history": {"createdBy": "them@example.com"}}]

        patches = {
            "get_local_folders": lambda _d: [
                {"path": "D:/E/Example Ridge", "name": "Example Ridge",
                 "code": None, "esxCount": 1, "totalSize": 10}],
            "get_local_esx_files": lambda _d: [
                {"path": "D:/E/Example Ridge/Example Ridge AP01.esx",
                 "name": "Example Ridge AP01", "folder": "Example Ridge",
                 "size": 10, "mtime": 1, "owner": "", "projectId": "d1",
                 "projectType": None}],
            "folder_inventory": lambda _p: {"srcCount": 0, "total": 1, "esx": 1,
                                            "plans": 0, "images": 0, "other": 0,
                                            "files": []},
            "not_matches_set": lambda: set(),
            "manual_matches_map": lambda: ({}, {}),
        }
        saved = {k: getattr(cm, k) for k in patches}
        for k, v in patches.items():
            setattr(cm, k, v)
        try:
            result = cm.build_sites_data(FakeApi(), "D:/E")
        finally:
            for k, v in saved.items():
                setattr(cm, k, v)

        pair = result["matched"][0]
        self.assertNotIn("owner", pair["cloud"],
                         "a cloud site now carries an owner - if Ekahau really "
                         "does share sites, the External wording needs "
                         "revisiting rather than this test deleting.")
        self.assertNotIn("owner", pair["local"],
                         "a local folder now carries an owner")
        #: And the project inside it is the one that is somebody else's.
        kid = pair["cloud"]["children"]["matched"][0]["cloud"]
        self.assertEqual("them@example.com", kid["owner"])

    def test_the_chip_does_not_claim_a_site_can_be_external(self):
        """The sentence he hovered. Asserted as a property - that the tooltip
        does not say the site itself can be somebody else's - rather than by
        pinning a phrasing, which would pin the next wrong one with it."""
        html = CLOUD_HTML.read_text(encoding="utf-8")
        m = re.search(r'data-filter="external"[^>]*title="([^"]+)"', html)
        self.assertIsNotNone(m, "the External chip has no tooltip at all")
        tip = m.group(1)
        self.assertNotIn("this can be the site itself", tip)
        #: It still has to explain why a site appears under a project filter.
        self.assertRegex(tip, r"inside it|projects? inside",
                         "the tooltip no longer says why a site is listed here")
