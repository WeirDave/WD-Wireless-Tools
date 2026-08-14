from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools.folder_organizer as organizer_module
from tools.folder_organizer import (
    DEFAULT_CONFIG,
    FolderOrganizer,
    _apply_rename,
    _classify,
    _esx_image_names,
    _esx_summary,
    _get_destinations,
    _sanitize_folder_name,
    _unique_path,
)

from tests.esx_factory import make_esx


class FolderOrganizerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = self.base / "projects"
        self.state = self.base / "state"
        self.root.mkdir()
        self.patchers = [
            patch.object(organizer_module, "CONFIG_DIR", self.state),
            patch.object(organizer_module, "ORGANIZER_CONFIG", self.state / "organizer_config.json"),
            patch.object(organizer_module, "UNDO_DIR", self.state / "undo"),
            patch.object(organizer_module, "ACORN_STATE_DIR", self.state / "acorn_state"),
        ]
        for p in self.patchers:
            p.start()
        organizer_module._ESX_SUMMARY_CACHE.clear()
        organizer_module._ESX_IMAGE_NAMES_CACHE.clear()
        self.organizer = FolderOrganizer()

    def tearDown(self):
        for p in reversed(self.patchers):
            p.stop()
        self.temp.cleanup()

    def make_site(self, name="SITE1 - Sample"):
        site = self.root / name
        site.mkdir()
        return site

    def test_classification_defaults_and_custom_override(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        self.assertEqual(_classify(Path("photo.JPG"), cfg), "images")
        self.assertEqual(_classify(Path("floor.pdf"), cfg), "floorplans")
        self.assertEqual(_classify(Path("validation report.pdf"), cfg), "reports")
        self.assertEqual(_classify(Path("assessment.json"), cfg), "reports")
        self.assertIsNone(_classify(Path("project.esx"), cfg))
        self.assertIsNone(_classify(Path("unknown.bin"), cfg))

        cfg["custom_destinations"] = [{
            "key": "data", "name": "data files", "exts": ["csv"],
            "pdf_keywords": [], "json_keywords": [],
        }]
        self.assertEqual(_classify(Path("results.csv"), cfg), "data")
        destinations = _get_destinations(cfg)
        self.assertEqual(destinations[-1]["name"], "data files")

    def test_rename_pipeline_and_safe_names(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["rename"] = {
            "strip_prefix": r"OLD[-_ ]*",
            "prefix": "{folder}_",
            "separator": "underscore",
            "regex_from": "Draft",
            "regex_to": "final",
            "case": "lower",
        }


        self.assertEqual(
            _apply_rename("OLD Draft Plan.PNG", "SITE9 - Sample", cfg),
            "SITE9 - Sample_final_plan.PNG",
        )
        self.assertEqual(_sanitize_folder_name('Bad<Name>.  '), "Bad-Name-")
        self.assertEqual(_sanitize_folder_name(".."), "")

    def test_rename_strip_suffix_and_prefix_suffix_tokens(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["rename"] = {"strip_suffix": r"\s*\(copy\)"}
        self.assertEqual(_apply_rename("photo (copy).jpg", "Site", cfg), "photo.jpg")

        cfg["rename"] = {"prefix": "{folder} - PD v1.0_", "suffix": "-FINAL"}
        self.assertEqual(
            _apply_rename("photo.jpg", "Springfield CA", cfg),
            "Springfield CA - PD v1.0_photo-FINAL.jpg",
        )

    def test_rename_case_and_separator_options(self):
        cfg = copy.deepcopy(DEFAULT_CONFIG)
        cfg["rename"] = {"case": "upper"}
        self.assertEqual(_apply_rename("my file.jpg", "Site", cfg), "MY FILE.jpg")
        cfg["rename"] = {"case": "title"}
        self.assertEqual(_apply_rename("my file name.jpg", "Site", cfg), "My File Name.jpg")
        cfg["rename"] = {"separator": "space"}
        self.assertEqual(_apply_rename("my_file-name.jpg", "Site", cfg), "my file name.jpg")
        cfg["rename"] = {"separator": "hyphen"}
        self.assertEqual(_apply_rename("my  file_name.jpg", "Site", cfg), "my-file-name.jpg")
        cfg["rename"] = {"separator": "spaced_hyphen"}
        self.assertEqual(_apply_rename("my_file-name.jpg", "Site", cfg), "my - file - name.jpg")
        cfg["rename"] = {"case": "sentence"}
        self.assertEqual(_apply_rename("MY FILE NAME.jpg", "Site", cfg), "My file name.jpg")

    def test_rename_migrates_legacy_config_keys(self):

        migrated = organizer_module._migrate_rename_cfg({
            "lowercase": True,
            "add_site_code": True,
            "collapse_spaces": True,
            "strip_prefix": "",
            "regex_from": "",
            "regex_to": "",
        })
        self.assertEqual(migrated, {
            "strip_prefix": "",
            "strip_suffix": "",
            "regex_from": "",
            "regex_to": "",
            "separator": "underscore",
            "case": "lower",
            "prefix": "{folder}_",
            "suffix": "",
        })

    def test_rename_migrates_v1_34_prepend_parent(self):
        migrated = organizer_module._migrate_rename_cfg({
            "strip_prefix": "",
            "prepend_parent": True,
            "regex_from": "",
            "regex_to": "",
            "separator": "",
            "case": "",
        })
        self.assertEqual(migrated["prefix"], "{folder}_")
        self.assertNotIn("prepend_parent", migrated)

    def test_detect_rename_style_matches_existing_files(self):
        site = self.make_site("SITE4 - Hyphens")
        (site / "floor-one.pdf").write_bytes(b"a")
        (site / "floor-two.pdf").write_bytes(b"a")
        (site / "ap-list.csv").write_bytes(b"a")
        r = self.organizer.detect_rename_style(str(self.root))
        self.assertTrue(r["ok"])
        self.assertEqual(r["separator"], "hyphen")

    def test_detect_rename_style_ties_leave_as_is(self):
        site = self.make_site("SITE5 - Mixed")
        (site / "floor one.pdf").write_bytes(b"a")
        (site / "floor_two.pdf").write_bytes(b"a")
        r = self.organizer.detect_rename_style(str(self.root))
        self.assertTrue(r["ok"])
        self.assertEqual(r["separator"], "")

    def test_unique_path_adds_incrementing_suffix(self):
        target = self.base / "photo.jpg"
        target.write_bytes(b"a")
        (self.base / "photo (1).jpg").write_bytes(b"b")
        self.assertEqual(_unique_path(target).name, "photo (2).jpg")

    def test_generated_esx_summary_and_image_references(self):
        esx = make_esx(self.base / "sample.esx", floors=2, aps=4,
                       measurements=5, surveys=2,
                       referenced_images=("Floor One.PNG", "map.jpg"))
        self.assertEqual(_esx_summary(esx), {
            "floors": 2, "aps": 4, "measurements": 5, "surveys": 2,
        })
        self.assertEqual(_esx_image_names(esx), {"floor one", "map"})
        broken = self.base / "broken.esx"
        broken.write_text("not a zip", encoding="utf-8")
        self.assertIsNone(_esx_summary(broken))

    def test_scan_execute_and_undo_round_trip(self):
        site = self.make_site()
        make_esx(site / "sample.esx", referenced_images=("floor-one.png",))
        (site / "photo.jpg").write_bytes(b"image")
        (site / "floor.pdf").write_bytes(b"plan")
        (site / "validation-report.pdf").write_bytes(b"report")
        (site / "notes.txt").write_text("notes", encoding="utf-8")
        (site / "unknown.bin").write_bytes(b"unknown")

        preview = self.organizer.scan(str(self.root))
        self.assertTrue(preview["ok"])
        self.assertEqual(preview["site_count"], 1)
        self.assertEqual(preview["totals"]["images"], 1)
        self.assertEqual(preview["totals"]["floorplans"], 1)
        self.assertEqual(preview["totals"]["reports"], 2)
        esx_entry = next(x for x in preview["sites"][0]["staying"] if x["ext"] == ".esx")
        self.assertEqual(esx_entry["esx"]["aps"], 2)

        result = self.organizer.execute(str(self.root))
        self.assertTrue(result["ok"])
        self.assertEqual(result["undo_count"], 4)
        self.assertTrue((site / "images" / "photo.jpg").is_file())
        self.assertTrue((site / "floorplans" / "floor.pdf").is_file())
        self.assertTrue((site / "reports" / "validation-report.pdf").is_file())
        self.assertTrue((site / "reports" / "notes.txt").is_file())
        self.assertTrue((site / "sample.esx").is_file())
        self.assertTrue((site / "unknown.bin").is_file())
        self.assertTrue(self.organizer.has_undo(str(self.root))["available"])

        undone = self.organizer.undo(str(self.root))
        self.assertEqual(undone["restored"], 4)
        self.assertEqual(undone["errors"], 0)
        for name in ("photo.jpg", "floor.pdf", "validation-report.pdf", "notes.txt"):
            self.assertTrue((site / name).is_file(), name)
        self.assertFalse((site / "images").exists())
        self.assertFalse((site / "floorplans").exists())
        self.assertFalse((site / "reports").exists())
        self.assertFalse(self.organizer.has_undo(str(self.root))["available"])

    def test_execute_respects_exclusion_override_and_collision(self):
        site = self.make_site()
        (site / "images").mkdir()
        (site / "images" / "photo.jpg").write_bytes(b"existing")
        (site / "photo.jpg").write_bytes(b"new")
        (site / "floor.pdf").write_bytes(b"plan")
        (site / "skip.txt").write_text("skip", encoding="utf-8")

        result = self.organizer.execute(
            str(self.root),
            excluded=[{"folder": site.name, "name": "skip.txt"}],
            overrides=[{"folder": site.name, "name": "floor.pdf", "target": "reports"}],
        )
        self.assertTrue(result["ok"])
        self.assertTrue((site / "images" / "photo (1).jpg").is_file())
        self.assertTrue((site / "reports" / "floor.pdf").is_file())
        self.assertTrue((site / "skip.txt").is_file())

        undone = self.organizer.undo(str(self.root))
        self.assertEqual(undone["restored"], 2)
        self.assertEqual((site / "images" / "photo.jpg").read_bytes(), b"existing")
        self.assertEqual((site / "photo.jpg").read_bytes(), b"new")

    def test_duplicate_detection_across_sites(self):
        one = self.make_site("SITE1")
        two = self.make_site("SITE2")
        (one / "same.pdf").write_bytes(b"identical")
        (two / "same.pdf").write_bytes(b"identical")
        preview = self.organizer.scan(str(self.root))
        self.assertEqual(preview["duplicate_count"], 1)
        self.assertEqual(preview["duplicates"][0]["site_count"], 2)

    def test_create_project_folder_with_selected_subfolders(self):
        result = self.organizer.create_project_folder(
            "SITE3 - New", str(self.root), ["images", "Installer Photos", "images", ".."]
        )
        self.assertTrue(result["ok"])
        target = Path(result["path"])
        self.assertTrue((target / "images").is_dir())
        self.assertTrue((target / "Installer Photos").is_dir())
        self.assertFalse((target / "reports").exists())

    def test_config_persistence_is_isolated_to_test_state(self):
        changed = self.organizer.set_config({"subfolder_names": {
            "images": "photos", "floorplans": "plans", "reports": "docs",
        }})
        self.assertTrue(changed["ok"])
        loaded = self.organizer.get_config()["config"]
        self.assertEqual(loaded["subfolder_names"]["images"], "photos")
        self.assertTrue((self.state / "organizer_config.json").is_file())
        reset = self.organizer.reset_config()["config"]
        self.assertEqual(reset["subfolder_names"]["images"], "images")

    def test_flat_root_folder_organize_and_undo(self):
        flat = self.base / "flat"
        flat.mkdir()
        (flat / "photo.png").write_bytes(b"image")
        (flat / "report.txt").write_text("report", encoding="utf-8")
        result = self.organizer.execute(str(flat))
        self.assertEqual(result["undo_count"], 2)
        self.assertTrue((flat / "images" / "photo.png").is_file())
        self.assertTrue((flat / "reports" / "report.txt").is_file())
        self.assertEqual(self.organizer.undo(str(flat))["restored"], 2)

    def test_undo_refuses_to_overwrite_recreated_original(self):
        site = self.make_site()
        (site / "photo.jpg").write_bytes(b"moved-version")
        self.organizer.execute(str(self.root))
        (site / "photo.jpg").write_bytes(b"new-version")
        result = self.organizer.undo(str(self.root))
        self.assertEqual(result["restored"], 0)
        self.assertEqual(result["skipped"], 1)
        self.assertEqual((site / "photo.jpg").read_bytes(), b"new-version")
        self.assertEqual((site / "images" / "photo.jpg").read_bytes(), b"moved-version")

    def test_migrate_subfolders_renames_and_skips_collisions(self):
        one = self.make_site("SITE1")
        two = self.make_site("SITE2")
        (one / "images").mkdir()
        (two / "images").mkdir()
        (two / "photos").mkdir()
        result = self.organizer.migrate_subfolders(str(self.root), {"images": "photos"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["renamed"], 1)
        self.assertEqual(result["skipped"], 1)
        self.assertTrue((one / "photos").is_dir())
        self.assertTrue((two / "images").is_dir())

    def test_save_esx_info_writes_acorn_with_floor_names(self):
        esx = make_esx(self.base / "sample.esx", floors=3)
        result = self.organizer.save_esx_info(str(esx))
        self.assertTrue(result["ok"])
        self.assertEqual(result["floor_count"], 3)
        self.assertEqual(result["floors"], ["Floor 1", "Floor 2", "Floor 3"])
        acorn = Path(result["path"])
        self.assertEqual(acorn.name, "sample - Acorn.txt")
        self.assertTrue(acorn.is_file())
        content = acorn.read_text(encoding="utf-8")
        self.assertIn("  1. Floor 1", content)
        self.assertIn("  3. Floor 3", content)
        self.assertIn("FLOOR PLANS (3)", content)
        self.assertTrue(content.isascii())
        self.assertIn("=" * organizer_module._ACORN_WIDTH, content)
        self.assertIn("SUMMARY", content)
        self.assertIn("Floor plans:   3", content)
        self.assertNotIn("STATUS:", content)
        self.assertEqual(result["status"], "first")

    def test_save_esx_info_detects_changes_between_saves(self):
        esx_path = self.base / "sample.esx"
        make_esx(esx_path, floors=2, aps=2)
        first = self.organizer.save_esx_info(str(esx_path))
        self.assertEqual(first["status"], "first")


        make_esx(esx_path, floors=3, aps=4)
        second = self.organizer.save_esx_info(str(esx_path))
        self.assertEqual(second["status"], "changed")
        content = Path(second["path"]).read_text(encoding="utf-8")
        self.assertIn("STATUS: CHANGED since last note", content)
        self.assertIn("Added floor plan: Floor 3", content)
        self.assertIn("Access points: 2 -> 4 (+2)", content)


        third = self.organizer.save_esx_info(str(esx_path))
        self.assertEqual(third["status"], "unchanged")
        content = Path(third["path"]).read_text(encoding="utf-8")
        self.assertIn("STATUS: No changes since last note", content)

    def test_save_esx_info_rejects_non_esx(self):
        broken = self.base / "broken.esx"
        broken.write_text("not a zip", encoding="utf-8")
        result = self.organizer.save_esx_info(str(broken))
        self.assertFalse(result["ok"])

    def test_extract_floorplans_also_refreshes_acorn(self):
        esx = make_esx(self.base / "sample.esx", floors=1,
                       referenced_images=("Floor 1.png",))
        floors = self.organizer.list_floorplans(str(esx))["floors"]
        self.assertFalse(floors[0]["available"])

        result = self.organizer.extract_floorplans(str(esx), floor_ids=[floors[0]["id"]])
        self.assertTrue(result["ok"])
        self.assertIsNotNone(result["acorn_path"])
        self.assertTrue(Path(result["acorn_path"]).is_file())

    def test_suggest_apply_grouping_and_undo(self):
        flat = self.base / "downloads"
        flat.mkdir()
        for name in ("SITE1-plan.pdf", "SITE1-photo.jpg", "SITE2-plan.pdf", "misc.txt"):
            (flat / name).write_text(name, encoding="utf-8")
        suggested = self.organizer.suggest_groups(str(flat))
        self.assertEqual(len(suggested["candidates"]), 1)
        self.assertEqual(suggested["candidates"][0]["prefix"], "SITE1")
        files = [item["name"] for item in suggested["candidates"][0]["files"]]
        applied = self.organizer.apply_grouping(str(flat), [{
            "prefix": "SITE1", "folder_name": "SITE1 - Sample", "files": files,
        }])
        self.assertEqual(applied["moved"], 2)
        self.assertTrue((flat / "SITE1 - Sample" / "SITE1-plan.pdf").is_file())
        undone = self.organizer.undo(str(flat))
        self.assertEqual(undone["restored"], 2)
        self.assertFalse((flat / "SITE1 - Sample").exists())


if __name__ == "__main__":
    unittest.main()
