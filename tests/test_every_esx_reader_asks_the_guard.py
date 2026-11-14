"""Every reader of an `.esx` asks whether reading it is sane - not just three.

`esx_guard.check` ran on the three upload routes (PlanTrim, Capacity, Prep) and
nowhere else. The folder scans, the compare, the rewrite, the trimmer and the
wall tools read members out of archives that come from a shared folder or down
from the cloud just as freely, so a crafted `.esx` sitting in a scanned folder
could ask for gigabytes without ever being opened by hand.

These tests build an archive the guard refuses (the limit is lowered to two
entries so the archive can be tiny) and run each reader against it. The question
asked is not "did it raise" - several readers are written to swallow an
unreadable file and carry on - but "did it read a single member": `ZipFile.read`
is counted, and the answer has to be none.
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

from tools import (capacity_profiles, cloud_manager, esx_compare, esx_guard,
                   esx_survey_data, esx_trimmer, folder_organizer,
                   prep_pipeline, wall_audit, wall_inject)


class EveryReaderAsksTheGuardTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-guard-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.esx = self.tmp / "hostile.esx"
        with zipfile.ZipFile(self.esx, "w") as z:
            z.writestr("project.json", json.dumps({"project": {"name": "p"}}))
            z.writestr("floorPlans.json", json.dumps({"floorPlans": []}))
            z.writestr("wallTypes.json", json.dumps({"wallTypes": []}))
            z.writestr("areas.json", json.dumps({"areas": []}))
        self.limit = mock.patch.object(esx_guard, "MAX_MEMBERS", 2)
        self.limit.start()
        self.addCleanup(self.limit.stop)
        self.reads = 0
        real = zipfile.ZipFile.read

        def counted(zf, *a, **k):
            self.reads += 1
            return real(zf, *a, **k)

        p = mock.patch.object(zipfile.ZipFile, "read", counted)
        p.start()
        self.addCleanup(p.stop)

    def _attempt(self, fn, *a, **k):
        try:
            fn(*a, **k)
        except Exception:
            pass
        return self.reads

    def test_the_guard_refuses_this_archive(self):
        with self.assertRaises(esx_guard.HostileArchive):
            esx_guard.check(self.esx)

    def test_a_refusal_is_a_bad_zip_so_existing_handlers_take_it(self):
        self.assertTrue(issubclass(esx_guard.HostileArchive, zipfile.BadZipFile))

    def test_the_folder_scan_readers(self):
        self.assertEqual(0, self._attempt(folder_organizer._esx_image_names, self.esx))
        self.assertEqual(0, self._attempt(folder_organizer._esx_extracted_stems, self.esx))
        self.assertEqual(0, self._attempt(folder_organizer._esx_summary, self.esx))

    def test_the_local_listing_metadata(self):
        self.assertEqual(0, self._attempt(cloud_manager._esx_meta, str(self.esx), 1))

    def test_the_rewrite(self):
        out = cloud_manager._rewrite_project_json(self.esx, lambda p, d: True)
        self.assertIn("error", out)
        self.assertEqual(0, self.reads)

    def test_the_compare(self):
        data = self.esx.read_bytes()
        self.reads = 0
        self.assertEqual(0, self._attempt(esx_compare.compare_esx, data, data))

    def test_the_survey_data_readers(self):
        self.assertEqual(0, self._attempt(esx_survey_data.missing_in_file, self.esx))
        self.assertEqual(0, self._attempt(
            esx_survey_data.missing_in_bytes, self.esx.read_bytes()))

    def test_the_trimmer(self):
        self.assertEqual(0, self._attempt(esx_trimmer.analyze, self.esx))
        self.assertEqual(0, self._attempt(
            esx_trimmer.trim, self.esx, self.tmp / "out.esx"))

    def test_the_wall_tools(self):
        self.assertEqual(0, self._attempt(wall_inject._read_members, self.esx))
        self.assertEqual(0, self._attempt(wall_audit.repair_project, self.esx,
                                          {"x": 1.0}))

    def test_prep_and_capacity(self):
        self.assertEqual(0, self._attempt(
            prep_pipeline._drop_areas, self.esx, self.tmp / "o.esx", {"a"}))
        self.assertEqual(0, self._attempt(
            capacity_profiles.apply_to, self.esx, self.tmp / "c.esx", {}, []))

    def test_an_ordinary_archive_is_still_read(self):
        with mock.patch.object(esx_guard, "MAX_MEMBERS", 50_000):
            with esx_guard.open_zip(self.esx) as z:
                self.assertIn("project.json", z.namelist())
                z.read("project.json")
        self.assertGreater(self.reads, 0)


class TheTrimmerStreamsWhatItDoesNotReadTests(unittest.TestCase):
    """The survey samples are most of a surveyed project and were read into
    memory on every analyze, plan and dry run, only to be written back."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-trim-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.esx = self.tmp / "p.esx"
        self.blob = bytes(range(256)) * 400
        with zipfile.ZipFile(self.esx, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("project.json", json.dumps({"project": {"name": "p"}}))
            z.writestr("floorPlans.json", json.dumps({"floorPlans": [
                {"id": "f1", "name": "Floor", "imageId": "i1",
                 "width": 100, "height": 100, "metersPerUnit": 1}]}))
            z.writestr("track-1.bin", self.blob)
            z.writestr("spectrum-1.bin", self.blob[::-1])

    def _reads_during(self, fn):
        names = []
        real = zipfile.ZipFile.read

        def counted(zf, name, *a, **k):
            names.append(name if isinstance(name, str) else name.filename)
            return real(zf, name, *a, **k)

        with mock.patch.object(zipfile.ZipFile, "read", counted):
            try:
                fn()
            except Exception:
                pass
        return names

    def test_analysing_never_reads_a_survey_sample(self):
        names = self._reads_during(lambda: esx_trimmer.analyze(self.esx))
        self.assertIn("floorPlans.json", names, "the analysis read nothing")
        self.assertFalse([n for n in names if n.endswith(".bin")], names)


if __name__ == "__main__":
    unittest.main()
