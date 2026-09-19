"""Fixing the third name - the one inside the file, that he cannot see.

There are three names on a matched row and only two are visible: the file on
disk, the project name stored in `project.json`, and the cloud project's name.
**Renaming a file on disk does not touch the one inside it.** So after renaming
a fleet of projects to a new naming convention, the two names he can see agree
and the hidden one still reads the old thing - and the comparison correctly,
uselessly, reports a difference:

    "Renamed only - the design is identical, the project just has a different
     name on each side"

...while he looks at two identical names. "which is not actually true, the
names are actually the same now."

Reporting it better is half the fix. The other half is being able to correct
it, because without that his whole fleet stays flagged for ever over a field
nothing he can reach will change. His counters read 29 out of sync and 97 local
folders, so the bulk path is the point rather than a nicety.

This writes to a real `.esx`, so what it has to get right is narrow and
absolute: change the name, change **nothing else**, and never leave the file in
a state worse than it started.
"""
from __future__ import annotations

import io
import json
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from tools import cloud_manager


def build_esx(path: Path, project_name="SITE1 Old Name", extra=None):
    members = {
        "version": b"2.0",
        "project.json": json.dumps({"project": {
            "id": "proj-uuid", "name": project_name, "title": project_name,
            "history": {"createdBy": "someone",
                        "modifiedAt": "2026-01-02T03:04:05Z"},
        }}).encode("utf-8"),
        "accessPoints.json": json.dumps({"accessPoints": [
            {"id": "ap-1", "name": "AP 1"}]}).encode("utf-8"),
        "floorPlans.json": json.dumps({"floorPlans": [
            {"id": "fp-1", "name": "Floor 1"}]}).encode("utf-8"),
        "image-img-1": b"PNGDATA" * 200,
    }
    if extra:
        members.update(extra)
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, raw in members.items():
            zf.writestr(name, raw)
    return members


def read_members(path: Path):
    with zipfile.ZipFile(path) as zf:
        return {n: zf.read(n) for n in zf.namelist()}


class ManagerHarness(cloud_manager.CloudManager):
    """The write path only needs the configured folder, not a cloud session."""

    def __init__(self, root):
        self.config = {"output_dir": str(root)}


class TheNameInsideTheFileCanBeCorrectedTests(unittest.TestCase):

    def setUp(self):
        self._td = TemporaryDirectory()
        self.root = Path(self._td.name)
        self.esx = self.root / "SITE1" / "SITE1 New Convention.esx"
        self.before = build_esx(self.esx)
        self.cm = ManagerHarness(self.root)

    def tearDown(self):
        self._td.cleanup()

    def test_it_sets_the_name_and_says_what_it_was(self):
        r = self.cm.set_internal_project_name(str(self.esx), "SITE1 New Convention")
        self.assertTrue(r.get("ok"), r)
        self.assertEqual("SITE1 New Convention", r["name"])
        self.assertEqual("SITE1 Old Name", r["previousName"])

        doc = json.loads(read_members(self.esx)["project.json"].decode("utf-8"))
        self.assertEqual("SITE1 New Convention", doc["project"]["name"])
        self.assertEqual("SITE1 New Convention", doc["project"]["title"])

    def test_it_changes_nothing_else_in_the_archive(self):
        """The whole risk. This is his live project; it must come back the same
        project with a corrected label, not a re-save."""
        self.cm.set_internal_project_name(str(self.esx), "SITE1 New Convention")
        after = read_members(self.esx)

        self.assertEqual(set(self.before), set(after), "members were added or lost")
        for name, raw in self.before.items():
            if name == "project.json":
                continue
            self.assertEqual(raw, after[name], name + " was modified")

    def test_the_rest_of_project_json_survives(self):
        """Only the two name fields move. The id in particular is what pairs
        the two sides, and losing it would unmatch the project."""
        self.cm.set_internal_project_name(str(self.esx), "Something Else")
        doc = json.loads(read_members(self.esx)["project.json"].decode("utf-8"))
        self.assertEqual("proj-uuid", doc["project"]["id"])
        self.assertEqual("someone", doc["project"]["history"]["createdBy"])
        self.assertEqual("2026-01-02T03:04:05Z",
                         doc["project"]["history"]["modifiedAt"])

    def test_the_folder_gains_no_file(self):
        """No copy is kept. The one thing this changes is the name inside the
        .esx, and the cloud project it is being matched to is holding that
        name - so a copy here would be a copy of something already elsewhere.
        What that makes load-bearing is the rebuild adding nothing: a surviving
        `.wd-rename.tmp` would be read by the next scan as a project nobody
        made."""
        folder = self.esx.parent
        before = sorted(p.name for p in folder.iterdir())
        r = self.cm.set_internal_project_name(str(self.esx), "SITE1 New Convention")
        self.assertTrue(r.get("ok"), r)
        self.assertNotIn("backup", r)
        self.assertEqual(sorted(p.name for p in folder.iterdir()), before)

    def test_nothing_is_written_when_the_path_is_outside_the_folder(self):
        """The containment check runs before anything is read or written: a
        path the page names that is not under the configured folder is refused
        outright, and the file it pointed at is left exactly as it was."""
        cm = ManagerHarness(self.root)
        cm.config["output_dir"] = str(self.root / "nope" / "missing")
        r = cm.set_internal_project_name(str(self.esx), "Whatever")
        self.assertIn("error", r)
        doc = json.loads(read_members(self.esx)["project.json"].decode("utf-8"))
        self.assertEqual("SITE1 Old Name", doc["project"]["name"])

    def test_setting_the_name_it_already_has_is_a_no_op(self):
        """His fleet will be part-done; running it twice must not churn files.

        `_rewrite_project_json` writes nothing at all when the mutation changes
        nothing - no temp file, no replace - which is what makes a re-run after
        an interruption free."""
        before = self.esx.read_bytes()
        r = self.cm.set_internal_project_name(str(self.esx), "SITE1 Old Name")
        self.assertTrue(r.get("ok"))
        self.assertTrue(r.get("unchanged"))
        self.assertEqual(self.esx.read_bytes(), before)

    def test_it_refuses_a_path_outside_the_configured_folder(self):
        outside = Path(self._td.name).parent / "elsewhere.esx"
        r = self.cm.set_internal_project_name(str(outside), "X")
        self.assertIn("error", r)

    def test_it_refuses_an_empty_name(self):
        r = self.cm.set_internal_project_name(str(self.esx), "   ")
        self.assertIn("error", r)

    def test_an_archive_without_a_project_record_is_refused_not_mangled(self):
        odd = self.root / "SITE1" / "odd.esx"
        with zipfile.ZipFile(odd, "w") as zf:
            zf.writestr("floorPlans.json", "{}")
        r = self.cm.set_internal_project_name(str(odd), "X")
        self.assertIn("error", r)
        self.assertEqual({"floorPlans.json"}, set(read_members(odd)))

    def test_the_metadata_cache_is_dropped_so_the_row_updates(self):
        """The name is read through a cache keyed by mtime. Leaving a stale
        entry would show the old name back on the next refresh and look like
        the fix had failed."""
        mtime = int(self.esx.stat().st_mtime)
        cloud_manager._esx_meta(self.esx, mtime)
        self.assertIn(str(self.esx), cloud_manager._ESX_META_CACHE)
        self.cm.set_internal_project_name(str(self.esx), "SITE1 New Convention")
        self.assertNotIn(str(self.esx), cloud_manager._ESX_META_CACHE)

    def test_the_comparison_then_reports_the_names_agreeing(self):
        """End to end: the state he is in, corrected, checked with the same
        code the row uses."""
        from tools.esx_compare import compare_esx

        cloud = io.BytesIO()
        with zipfile.ZipFile(cloud, "w", zipfile.ZIP_DEFLATED) as zf:
            for name, raw in self.before.items():
                if name == "project.json":
                    raw = json.dumps({"project": {
                        "id": "proj-uuid", "name": "SITE1 New Convention",
                        "title": "SITE1 New Convention",
                        "history": {"createdBy": "someone",
                                    "modifiedAt": "2026-09-17T12:00:00Z"},
                    }}).encode("utf-8")
                zf.writestr(name, raw)
        cloud_bytes = cloud.getvalue()

        before = compare_esx(self.esx.read_bytes(), cloud_bytes,
                             local_file_stem=self.esx.stem)
        self.assertEqual("internal_only", before["nameState"])
        self.assertIn("project name inside the file", before["summary"])

        self.cm.set_internal_project_name(str(self.esx), "SITE1 New Convention")

        after = compare_esx(self.esx.read_bytes(), cloud_bytes,
                            local_file_stem=self.esx.stem)
        self.assertEqual("same", after["nameState"])
        self.assertTrue(after["identical"])


if __name__ == "__main__":
    unittest.main()
