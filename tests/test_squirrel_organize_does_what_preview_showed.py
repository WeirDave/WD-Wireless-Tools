"""Squirrel's Organize does what its Preview showed, and survives a bad folder.

Each class here is one defect a review found by running the code:

* one folder that could not be written stopped Organize part-way through,
  after earlier sites had moved, and the undo log was never written;
* one folder that could not be read failed the whole scan;
* Preview fell back to the root as a site whenever no site had anything to
  show, Organize only when there were no site folders - so loose files beside
  an empty site folder were previewed as moves and then left alone;
* in root-as-site mode the label "  (root folder)" reached file names through
  a ``{folder}_`` prefix rule;
* a run that moved nothing deleted the previous run's undo log;
* two files bound for one name both previewed unchanged, and Organize renamed
  the second.

Folder and file names are invented.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools.folder_organizer as organizer_module
from tools.folder_organizer import DEFAULT_CONFIG, FolderOrganizer


def _tree(p: Path) -> list:
    return sorted(x.relative_to(p).as_posix() for x in p.rglob("*"))


class _Base(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "projects"
        self.root.mkdir()
        state = self.base / "state"
        self.patchers = [
            patch.object(organizer_module, "CONFIG_DIR", state),
            patch.object(organizer_module, "ORGANIZER_CONFIG",
                         state / "organizer_config.json"),
            patch.object(organizer_module, "UNDO_DIR", state / "undo"),
            patch.object(organizer_module, "ACORN_STATE_DIR",
                         state / "acorn_state"),
        ]
        for p in self.patchers:
            p.start()
        self.org = FolderOrganizer()

    def tearDown(self):
        for p in reversed(self.patchers):
            p.stop()
        self.temp.cleanup()

    def rename_rules(self, **rules):
        cfg = organizer_module._load_config()
        cfg["rename"] = {**DEFAULT_CONFIG["rename"], **rules}
        organizer_module._save_config(cfg)

    def site(self, name, *files):
        d = self.root / name
        d.mkdir(parents=True, exist_ok=True)
        for f in files:
            (d / f).write_text(name + "/" + f)
        return d


class OneFolderThatCannotBeWrittenDoesNotStopTheRest(_Base):

    def test_the_other_sites_are_organized_and_the_failure_is_named(self):
        self.site("Alpha Site", "a.png")
        self.site("Zulu Site", "z.png")
        real_mkdir = Path.mkdir

        def refusing(path, *a, **k):
            if path.parent.name == "Zulu Site":
                raise PermissionError(13, "Access is denied", str(path))
            return real_mkdir(path, *a, **k)

        with patch.object(Path, "mkdir", refusing):
            r = self.org.execute(str(self.root), [], [])

        self.assertTrue(r["ok"])
        self.assertEqual(_tree(self.root / "Alpha Site"),
                         ["floorplans", "images", "images/a.png", "reports"])
        zulu = next(s for s in r["sites"] if s["folder"] == "Zulu Site")
        self.assertEqual(zulu["moves"][0]["status"], "error")
        self.assertIsNone(zulu["moves"][0]["target"])
        self.assertIn("denied", zulu["moves"][0]["error"])
        self.assertEqual(r["totals"]["errors"], 1)

    def test_what_moved_before_the_failure_can_be_undone(self):
        self.site("Alpha Site", "a.png")
        self.site("Zulu Site", "z.png")
        real_mkdir = Path.mkdir

        def refusing(path, *a, **k):
            if path.parent.name == "Zulu Site":
                raise PermissionError(13, "Access is denied", str(path))
            return real_mkdir(path, *a, **k)

        with patch.object(Path, "mkdir", refusing):
            self.org.execute(str(self.root), [], [])
        self.assertEqual(self.org.has_undo(str(self.root))["count"], 1)
        self.org.undo(str(self.root))
        self.assertTrue((self.root / "Alpha Site" / "a.png").is_file())

    def test_an_unexpected_exception_still_leaves_an_undo_log(self):
        """The log is written in a `finally`: a crash that is not an OSError
        still propagates, but the moves already made stay undoable."""
        self.site("Alpha Site", "a.png")
        self.site("Zulu Site", "z.png")
        real_classify = organizer_module._classify

        def exploding(file, cfg):
            if file.parent.name == "Zulu Site":
                raise ValueError("invented failure")
            return real_classify(file, cfg)

        with patch.object(organizer_module, "_classify", exploding):
            with self.assertRaises(ValueError):
                self.org.execute(str(self.root), [], [])
        self.assertTrue((self.root / "Alpha Site" / "images" / "a.png").is_file())
        self.assertEqual(self.org.has_undo(str(self.root))["count"], 1)


class OneFolderThatCannotBeReadDoesNotFailTheScan(_Base):

    def _locked(self, name):
        real = Path.iterdir

        def iterdir(path):
            if path.name == name:
                raise PermissionError(13, "Access is denied", str(path))
            return real(path)
        return patch.object(Path, "iterdir", iterdir)

    def test_the_scan_skips_it_and_says_why(self):
        self.site("Echo Site", "a.png")
        self.site("Locked Site", "b.png")
        with self._locked("Locked Site"):
            r = self.org.scan(str(self.root))
        self.assertTrue(r["ok"])
        self.assertEqual([s["folder"] for s in r["sites"]], ["Echo Site"])
        self.assertEqual([u["folder"] for u in r["unreadable"]], ["Locked Site"])
        self.assertIn("denied", r["unreadable"][0]["reason"])
        self.assertEqual(r["totals"]["images"], 1)

    def test_duplicate_detection_tolerates_it_too(self):
        a = self.site("Echo Site", "a.png")
        b = self.site("Locked Site", "a.png")
        with self._locked("Locked Site"):
            groups = self.org._find_duplicates(
                [a, b], organizer_module._load_config())
        self.assertEqual(groups, [])


class PreviewAndOrganizeUseOneRuleForTheRoot(_Base):

    def test_loose_files_beside_an_empty_site_folder(self):
        (self.root / "Alpha Site").mkdir()
        (self.root / "plan.pdf").write_text("x")
        (self.root / "pic.png").write_text("y")
        scan = self.org.scan(str(self.root))
        previewed = [m["name"] for s in scan["sites"] for m in s["moves"]]
        done = self.org.execute(str(self.root), [], [])
        moved = [m["name"] for s in done["sites"] for m in s["moves"]
                 if m["status"] == "moved"]
        self.assertEqual(previewed, moved)
        self.assertEqual(previewed, [])

    def test_a_root_with_no_site_folders_is_the_site_in_both(self):
        (self.root / "pic.png").write_text("y")
        scan = self.org.scan(str(self.root))
        self.assertEqual([m["name"] for m in scan["sites"][0]["moves"]],
                         ["pic.png"])
        done = self.org.execute(str(self.root), [], [])
        self.assertEqual([m["name"] for s in done["sites"] for m in s["moves"]
                          if m["status"] == "moved"], ["pic.png"])


class TheRootLabelStaysOutOfFileNames(_Base):

    def test_a_folder_prefix_in_root_mode_uses_the_folder_name(self):
        root = self.base / "Bravo"
        root.mkdir()
        (root / "pic.png").write_text("y")
        self.rename_rules(prefix="{folder}_")
        scan = self.org.scan(str(root))
        self.assertEqual(scan["sites"][0]["moves"][0]["renamed_to"],
                         "Bravo_pic.png")
        self.org.execute(str(root), [], [])
        self.assertEqual(sorted(p.name for p in (root / "images").iterdir()),
                         ["Bravo_pic.png"])

    def test_an_exclusion_still_matches_the_root_label(self):
        root = self.base / "Bravo"
        root.mkdir()
        (root / "pic.png").write_text("y")
        label = self.org.scan(str(root))["sites"][0]["folder"]
        self.org.execute(str(root), [{"folder": label, "name": "pic.png"}], [])
        self.assertTrue((root / "pic.png").is_file())


class ARunThatMovesNothingKeepsTheUndo(_Base):

    def test_the_previous_organize_can_still_be_undone(self):
        self.site("Delta Site", "a.png")
        first = self.org.execute(str(self.root), [], [])
        self.assertTrue(first["undo_available"])
        second = self.org.execute(str(self.root), [], [])
        self.assertTrue(second["undo_available"])
        self.assertTrue(self.org.has_undo(str(self.root))["available"])
        self.org.undo(str(self.root))
        self.assertTrue((self.root / "Delta Site" / "a.png").is_file())


class PreviewShowsTheNameOrganizeWillUse(_Base):

    def test_two_files_bound_for_one_name(self):
        self.site("Charlie Site", "old_x.png", "x.png")
        self.rename_rules(strip_prefix="old_")
        scan = self.org.scan(str(self.root))
        previewed = {m["name"]: m["renamed_to"]
                     for m in scan["sites"][0]["moves"]}
        done = self.org.execute(str(self.root), [], [])
        applied = {m["name"]: m["renamed_to"]
                   for m in done["sites"][0]["moves"]}
        self.assertEqual(previewed, applied)
        self.assertEqual(previewed, {"old_x.png": "x.png",
                                     "x.png": "x (1).png"})


class SquirrelBulkRenameAppliesACaseOnlyChange(_Base):
    """NTFS answers `exists()` without regard to case, so the target of a
    case-only rename "exists" and is the file itself. Emulated here by making
    `Path.exists` case-insensitive, because CI runs this on Linux as well."""

    def test_case_only_rename_is_applied(self):
        d = self.site("November Site", "Floor Plan.png")
        real_exists = Path.exists

        def ci_exists(path, *a, **k):
            try:
                return any(c.name.casefold() == path.name.casefold()
                           for c in path.parent.iterdir())
            except OSError:
                return real_exists(path, *a, **k)

        with patch.object(Path, "exists", ci_exists):
            r = self.org.execute_bulk_rename(
                [{"path": str(d / "Floor Plan.png"),
                  "new_name": "floor plan.png"}])
        self.assertEqual(r["renamed"], 1, r)
        self.assertEqual(os.listdir(d), ["floor plan.png"])


if __name__ == "__main__":
    unittest.main()
