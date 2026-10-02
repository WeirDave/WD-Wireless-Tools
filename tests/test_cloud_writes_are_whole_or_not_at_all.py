"""A write that fails partway leaves the old file, not half of a new one.

Two places opened the file they were replacing with "w"/"wb", which truncates
it before a byte of the new content is written:

* **Download with "overwrite"** - a failure partway through left neither his
  local .esx nor the cloud's copy on disk. It now builds beside the target and
  renames over it, as `verify_replace_local` always has, and drops the cached
  metadata for that path so the next scan reads the new file.
* **The three decisions files** - not-a-match pairs, manual matches and the
  External overrides. A failed save emptied every decision in the file.

Each test makes the write fail and then reads back what is on disk.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from tools import cloud_manager as cm

SITE = "Rowan Terrace"


def _esx_bytes(pid: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        info = zipfile.ZipInfo("project.json", date_time=(2026, 9, 1, 0, 0, 0))
        z.writestr(info, json.dumps({"project": {"id": pid,
                                                 "name": "Rowan Terrace"}}))
    return buf.getvalue()


class _NotBytes:
    """Content the file object refuses partway through writing it."""


class _Api:
    def __init__(self, payload):
        self.payload = payload

    def download_project(self, pid, progress_cb=None):
        return {"esx": self.payload, "name": "Rowan Terrace"}


class _Mgr(cm.CloudManager):
    def __init__(self, api, out_dir):
        self.api = api
        self.config = {"output_dir": str(out_dir)}

    def _ensure(self):
        return True


class DownloadOverwriteIsAtomicTests(unittest.TestCase):

    def setUp(self):
        self.root = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.root, True)
        self.target = self.root / SITE / "Rowan Terrace.esx"
        self.target.parent.mkdir(parents=True)
        self.original = _esx_bytes("local-aaaa1")
        self.target.write_bytes(self.original)

    def test_a_failed_overwrite_leaves_the_local_file_as_it_was(self):
        out = _Mgr(_Api(_NotBytes()), self.root).download_project(
            "c-1", SITE, on_exists="overwrite")
        self.assertTrue(out.get("error"), out)
        self.assertEqual(self.original, self.target.read_bytes(),
                         "the local .esx was truncated by a failed overwrite")
        self.assertEqual(["Rowan Terrace.esx"],
                         sorted(p.name for p in self.target.parent.iterdir()
                                if p.is_file()),
                         "a temporary file was left behind")

    def test_a_successful_overwrite_is_read_back_as_the_new_project(self):
        """Same size, same second - the case the metadata cache would serve
        the previous project's id for if the entry were not dropped."""
        stamp = 1790000000
        os.utime(self.target, (stamp, stamp))
        self.assertEqual("local-aaaa1", cm._esx_meta(self.target, stamp)["projectId"])

        new = _esx_bytes("cloud-bbbb2")
        self.assertEqual(len(new), len(self.original))
        out = _Mgr(_Api(new), self.root).download_project(
            "c-1", SITE, on_exists="overwrite")
        self.assertTrue(out.get("ok"), out)
        self.assertTrue(out.get("replaced"))
        self.assertEqual(new, self.target.read_bytes())
        os.utime(self.target, (stamp, stamp))
        self.assertEqual("cloud-bbbb2", cm._esx_meta(self.target, stamp)["projectId"])


class DecisionFilesSurviveAFailedSaveTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        for name, fname in (("NOT_MATCH_FILE", "not_matches.json"),
                            ("MANUAL_MATCH_FILE", "manual_matches.json"),
                            ("EXTERNAL_OVERRIDE_FILE", "external_overrides.json")):
            p = mock.patch.object(cm, name, self.tmp / fname)
            p.start()
            self.addCleanup(p.stop)
        p = mock.patch.object(cm, "CONFIG_DIR", self.tmp)
        p.start()
        self.addCleanup(p.stop)

    def _check(self, save, load, good, bad):
        save(good)
        before = load()
        self.assertTrue(before, "the first save wrote nothing")
        with self.assertRaises(TypeError):
            save(bad)
        self.assertEqual(before, load(), "a failed save destroyed the file")

    def test_not_matches(self):
        self._check(cm.save_not_matches, cm.load_not_matches,
                    [{"cloudId": "c-1", "localPath": "D:/a/One.esx"}],
                    [{"cloudId": "c-2", "localPath": "D:/a/Two.esx",
                      "junk": _NotBytes()}])

    def test_manual_matches(self):
        self._check(cm.save_manual_matches, cm.load_manual_matches,
                    [{"cloudId": "c-1", "localPath": "D:/a/One.esx"}],
                    [{"cloudId": "c-2", "localPath": "D:/a/Two.esx",
                      "junk": _NotBytes()}])

    def test_external_overrides(self):
        self._check(cm.save_external_overrides, cm.load_external_overrides,
                    [{"key": "c:c-1", "value": "external"}],
                    [{"key": "c:c-2", "value": "mine", "junk": _NotBytes()}])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
