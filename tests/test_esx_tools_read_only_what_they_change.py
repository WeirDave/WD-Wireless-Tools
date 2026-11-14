"""Wall repair, wall injection and the compare read one member at a time.

They used to read every member of the project into memory first - for a
surveyed project that is mostly sample files nobody here looks at - and write
them all back out. Only the one document each tool changes is read now, and the
rest passes from the source archive to the copy a member at a time.

The tests run the real tools over a real archive and record which members were
read, and then check that nothing outside the change moved by a byte.
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

from tools import esx_compare, esx_guard, wall_audit, wall_inject

SAMPLES = b"\x00\x01\x02survey-samples" * 500


def _wall(name, **extra):
    return {"id": "id-" + name, "name": name, "key": name, "lowerEdge": 0,
            "thickness": 0.1, "color": "#B07842", **extra}


def _make(path: Path, walls):
    members = {
        "project.json": json.dumps({"project": {"name": "Fixture"}}),
        "wallTypes.json": json.dumps({"wallTypes": walls}),
        "wallSegments.json": json.dumps({"wallSegments": []}),
        "track-1.bin": SAMPLES,
        "image-floor.png": b"\x89PNG-not-really",
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, blob in members.items():
            z.writestr(name, blob)
    return path


def _everything(path):
    with zipfile.ZipFile(path) as z:
        return {n: z.read(n) for n in z.namelist()}


class _Recording:
    """Names of the members read through `ZipFile.read` while it is active."""

    def __enter__(self):
        self.read = []
        real = zipfile.ZipFile.read
        seen = self.read

        def spy(zf, name, *a, **k):
            seen.append(name if isinstance(name, str) else name.filename)
            return real(zf, name, *a, **k)

        self._patch = mock.patch.object(zipfile.ZipFile, "read", spy)
        self._patch.start()
        return self.read

    def __exit__(self, *exc):
        self._patch.stop()


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-onemember-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)


class WallInjectionTests(_Tmp):

    def test_planning_reads_only_the_wall_types(self):
        esx = _make(self.tmp / "a.esx", [_wall("Concrete")])
        with _Recording() as read:
            wall_inject.plan_injection(esx, [_wall("Glass")])
        self.assertEqual(["wallTypes.json"], read)

    def test_the_rest_of_the_project_is_carried_across_untouched(self):
        esx = _make(self.tmp / "a.esx", [_wall("Concrete")])
        before = _everything(esx)
        report = wall_inject.inject(esx, [_wall("Glass")])
        self.assertTrue(report.get("written"), report)
        after = _everything(esx)
        self.assertEqual(list(before), list(after), "members and their order")
        for name in before:
            if name != "wallTypes.json":
                self.assertEqual(before[name], after[name], name)
        names = [w["name"] for w in json.loads(after["wallTypes.json"])["wallTypes"]]
        self.assertEqual(["Concrete", "Glass"], names)

    def test_a_copy_leaves_the_source_alone(self):
        esx = _make(self.tmp / "a.esx", [_wall("Concrete")])
        before = esx.read_bytes()
        out = self.tmp / "copy.esx"
        wall_inject.inject(esx, [_wall("Glass")], dest=out)
        self.assertEqual(before, esx.read_bytes())
        self.assertEqual(SAMPLES, _everything(out)["track-1.bin"])


class WallRepairTests(_Tmp):

    def test_repair_reads_only_the_wall_types_and_changes_only_them(self):
        esx = _make(self.tmp / "a.esx", [_wall("Concrete")])
        before = _everything(esx)
        with _Recording() as read:
            # The write copies the other members, which does read them one at
            # a time; the question for the read phase is what it asked for
            # before anything was written.
            first = []
            real_copy = esx_guard.copy_with_replacements

            def watch(src, dest, replaced):
                first.extend(read)
                return real_copy(src, dest, replaced)

            with mock.patch.object(esx_guard, "copy_with_replacements", watch):
                result = wall_audit.repair_project(esx, {"concrete": 3.0})
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(["wallTypes.json"], first)
        after = _everything(esx)
        for name in before:
            if name != "wallTypes.json":
                self.assertEqual(before[name], after[name], name)
        self.assertEqual(3.0, json.loads(after["wallTypes.json"])
                         ["wallTypes"][0]["upperEdge"])


class CopyWithReplacementsTests(_Tmp):

    def test_a_replaced_member_is_swapped_and_a_new_one_is_added(self):
        esx = _make(self.tmp / "a.esx", [_wall("Concrete")])
        out = self.tmp / "out.esx"
        esx_guard.copy_with_replacements(
            esx, out, {"wallTypes.json": b"{}", "extra.json": b"[]"})
        got = _everything(out)
        self.assertEqual(b"{}", got["wallTypes.json"])
        self.assertEqual(b"[]", got["extra.json"])
        self.assertEqual(SAMPLES, got["track-1.bin"])

    def test_an_archive_the_guard_refuses_is_not_copied(self):
        esx = _make(self.tmp / "a.esx", [_wall("Concrete")])
        with mock.patch.object(esx_guard, "MAX_MEMBERS", 2):
            with self.assertRaises(esx_guard.HostileArchive):
                esx_guard.copy_with_replacements(esx, self.tmp / "out.esx", {})


class CompareTests(_Tmp):

    def test_members_are_not_read_until_they_are_asked_for(self):
        esx = _make(self.tmp / "a.esx", [_wall("Concrete")])
        with zipfile.ZipFile(esx) as z, _Recording() as read:
            view = esx_compare._MemberView(z)
            self.assertEqual([], read, "building the view must read nothing")
            self.assertIn("track-1.bin", view)
            self.assertEqual(SAMPLES, view["track-1.bin"])
            self.assertEqual(["track-1.bin"], read)

    def test_two_archives_still_compare(self):
        a = _make(self.tmp / "a.esx", [_wall("Concrete")])
        b = _make(self.tmp / "b.esx", [_wall("Concrete"), _wall("Glass")])
        same = esx_compare.compare_esx(a.read_bytes(), a.read_bytes())
        self.assertTrue(same["identical"], same)
        diff = esx_compare.compare_esx(a.read_bytes(), b.read_bytes())
        self.assertTrue(diff["designDiffers"], diff)


if __name__ == "__main__":
    unittest.main()
