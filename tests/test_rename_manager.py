from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools.rename_manager as rm_module
from tools.rename_manager import (
    BUILTIN_TOKENS,
    DEFAULT_FILE_RULES,
    RenameManager,
    apply_file_rules,
    apply_token_format,
    migrate_rename_cfg,
    _split_ext,
    _sanitize_name,
    _title_case,
    _sentence_case,
)
from tools.settings import DEFAULTS, load_settings, save_settings, _migrate_settings


SAMPLE_CSV = """\
Site_ID,Site_Name,Address,City,Deprecated_Names
ACME-001,Downtown Office,123 Main St,Springfield,Old Downtown;Main St Office
ACME-002,North Campus,456 University Ave,Springfield,
ACME-003,Airport Terminal,789 Aviation Blvd,Capital City,Airport Site
"""


class RulePipelineTests(unittest.TestCase):
    """Tests for apply_file_rules — the rule-based rename pipeline."""

    def test_no_rules_returns_original(self):
        self.assertEqual(apply_file_rules("file.txt", "SITE", None), "file.txt")

    def test_empty_rules_returns_original(self):
        self.assertEqual(
            apply_file_rules("file.txt", "SITE", DEFAULT_FILE_RULES), "file.txt")

    def test_strip_prefix(self):
        rules = {**DEFAULT_FILE_RULES, "strip_prefix": r"IMG_"}
        self.assertEqual(apply_file_rules("IMG_001.jpg", "SITE", rules), "001.jpg")

    def test_strip_suffix(self):
        rules = {**DEFAULT_FILE_RULES, "strip_suffix": r"_final"}
        self.assertEqual(apply_file_rules("report_final.pdf", "SITE", rules), "report.pdf")

    def test_regex_replace(self):
        rules = {**DEFAULT_FILE_RULES, "regex_from": r"\d{4}", "regex_to": "XXXX"}
        self.assertEqual(apply_file_rules("scan2024.pdf", "SITE", rules), "scanXXXX.pdf")

    def test_separator_underscore(self):
        rules = {**DEFAULT_FILE_RULES, "separator": "underscore"}
        self.assertEqual(apply_file_rules("my file name.txt", "SITE", rules), "my_file_name.txt")

    def test_separator_hyphen(self):
        rules = {**DEFAULT_FILE_RULES, "separator": "hyphen"}
        self.assertEqual(apply_file_rules("my file name.txt", "SITE", rules), "my-file-name.txt")

    def test_separator_spaced_hyphen(self):
        rules = {**DEFAULT_FILE_RULES, "separator": "spaced_hyphen"}
        self.assertEqual(apply_file_rules("my_file_name.txt", "SITE", rules), "my - file - name.txt")

    def test_case_lower(self):
        rules = {**DEFAULT_FILE_RULES, "case": "lower"}
        self.assertEqual(apply_file_rules("MyFile.TXT", "SITE", rules), "myfile.TXT")

    def test_case_upper(self):
        rules = {**DEFAULT_FILE_RULES, "case": "upper"}
        self.assertEqual(apply_file_rules("myfile.txt", "SITE", rules), "MYFILE.txt")

    def test_case_title(self):
        rules = {**DEFAULT_FILE_RULES, "case": "title"}
        self.assertEqual(apply_file_rules("hello world.txt", "SITE", rules), "Hello World.txt")

    def test_case_sentence(self):
        rules = {**DEFAULT_FILE_RULES, "case": "sentence"}
        self.assertEqual(apply_file_rules("hello world.txt", "SITE", rules), "Hello world.txt")

    def test_prefix_with_folder_token(self):
        rules = {**DEFAULT_FILE_RULES, "prefix": "{folder}_"}
        self.assertEqual(apply_file_rules("scan.pdf", "SITE-A", rules), "SITE-A_scan.pdf")

    def test_suffix(self):
        rules = {**DEFAULT_FILE_RULES, "suffix": "_v2"}
        self.assertEqual(apply_file_rules("scan.pdf", "SITE", rules), "scan_v2.pdf")

    def test_full_pipeline_order(self):
        rules = {
            "strip_prefix": "RAW_",
            "strip_suffix": "",
            "regex_from": "",
            "regex_to": "",
            "separator": "underscore",
            "case": "lower",
            "prefix": "{folder}_",
            "suffix": "",
        }
        result = apply_file_rules("RAW_My File.jpg", "Site1", rules)
        self.assertEqual(result, "Site1_my_file.jpg")

    def test_nested_rename_key(self):
        cfg = {"rename": {**DEFAULT_FILE_RULES, "case": "upper"}}
        self.assertEqual(apply_file_rules("hello.txt", "SITE", cfg), "HELLO.txt")

    def test_invalid_regex_is_skipped(self):
        rules = {**DEFAULT_FILE_RULES, "strip_prefix": "[invalid"}
        self.assertEqual(apply_file_rules("[invalidfoo.txt", "S", rules), "[invalidfoo.txt")

    def test_extension_preserved(self):
        rules = {**DEFAULT_FILE_RULES, "case": "upper"}
        result = apply_file_rules("doc.pdf", "S", rules)
        self.assertTrue(result.endswith(".pdf"))


class MigrateRenameConfigTests(unittest.TestCase):
    """Tests for migrate_rename_cfg — legacy config translation."""

    def test_non_dict_returns_defaults(self):
        self.assertEqual(migrate_rename_cfg(None), DEFAULT_FILE_RULES)
        self.assertEqual(migrate_rename_cfg("bad"), DEFAULT_FILE_RULES)

    def test_lowercase_migrates_to_case(self):
        result = migrate_rename_cfg({"lowercase": True})
        self.assertEqual(result["case"], "lower")

    def test_add_site_code_migrates_to_prefix(self):
        result = migrate_rename_cfg({"add_site_code": True})
        self.assertEqual(result["prefix"], "{folder}_")

    def test_collapse_spaces_migrates_to_separator(self):
        result = migrate_rename_cfg({"collapse_spaces": True})
        self.assertEqual(result["separator"], "underscore")

    def test_already_migrated_passes_through(self):
        cfg = {**DEFAULT_FILE_RULES, "case": "title", "prefix": "X_"}
        result = migrate_rename_cfg(cfg)
        self.assertEqual(result["case"], "title")
        self.assertEqual(result["prefix"], "X_")


class TokenFormatTests(unittest.TestCase):
    """Tests for apply_token_format."""

    def test_basic_format(self):
        name, warnings = apply_token_format(
            "{site_code} {site_name}", " - ",
            {"site_code": "ACME-001", "site_name": "HQ"})
        self.assertEqual(name, "ACME-001 HQ")
        self.assertEqual(warnings, [])

    def test_literal_text_preserved(self):
        name, warnings = apply_token_format(
            "{site_code} - {site_name} ({city})", "",
            {"site_code": "ACME-001", "site_name": "HQ", "city": "Springfield"})
        self.assertEqual(name, "ACME-001 - HQ (Springfield)")
        self.assertEqual(warnings, [])

    def test_missing_token_warns(self):
        name, warnings = apply_token_format(
            "{site_code} {missing}", " - ",
            {"site_code": "ACME"})
        self.assertIn("__missing__", name)
        self.assertTrue(any("missing" in w for w in warnings))

    def test_empty_value_warns(self):
        name, warnings = apply_token_format(
            "{site_code}", " - ", {"site_code": ""})
        self.assertEqual(len(warnings), 1)

    def test_unsafe_chars_sanitized(self):
        name, _ = apply_token_format(
            "{x}", " ", {"x": 'file<>:name'})
        self.assertNotIn("<", name)
        self.assertNotIn(">", name)


class HelperTests(unittest.TestCase):
    def test_split_ext(self):
        self.assertEqual(_split_ext("file.txt"), ("file", ".txt"))
        self.assertEqual(_split_ext("no_ext"), ("no_ext", ""))

    def test_sanitize_name(self):
        self.assertEqual(_sanitize_name(""), "")
        self.assertEqual(_sanitize_name("a<b>c"), "a-b-c")
        self.assertEqual(_sanitize_name(".."), "")

    def test_title_case(self):
        self.assertEqual(_title_case("hello world"), "Hello World")

    def test_sentence_case(self):
        self.assertEqual(_sentence_case("HELLO WORLD"), "Hello world")


class RenameManagerTests(unittest.TestCase):
    """Integration tests for the RenameManager class."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.state = self.base / "state"
        self.root = self.base / "projects"
        self.root.mkdir()
        self.state.mkdir()
        self.patchers = [
            patch.object(rm_module, "CONFIG_DIR", self.state),
            patch.object(rm_module, "DIRECTORY_PATH", self.state / "site_directory.json"),
            patch.object(rm_module, "PROFILES_PATH", self.state / "rename_profiles.json"),
            patch.object(rm_module, "UNDO_DIR", self.state / "undo"),
            patch.object(rm_module, "_LEGACY_PROFILES_PATH", self.state / "old_profiles.json"),
            patch.object(rm_module, "_LEGACY_UNDO_DIR", self.state / "old_undo"),
        ]
        for p in self.patchers:
            p.start()
        self.mgr = RenameManager()

    def tearDown(self):
        for p in reversed(self.patchers):
            p.stop()
        self.temp.cleanup()

    def _load_sample(self):
        return self.mgr.load_directory(SAMPLE_CSV, {
            "primary": "Site_ID",
            "address": "Address",
            "deprecated": "Deprecated_Names",
        })

    def _make_folders(self, *names):
        for n in names:
            (self.root / n).mkdir(exist_ok=True)

    # ── get_tokens ──

    def test_builtin_tokens_always_present(self):
        r = self.mgr.get_tokens()
        keys = [t["key"] for t in r["tokens"]]
        self.assertIn("site_code", keys)
        self.assertIn("facility_code", keys)
        self.assertIn("date", keys)

    def test_csv_tokens_merged(self):
        self._load_sample()
        r = self.mgr.get_tokens()
        keys = [t["key"] for t in r["tokens"]]
        self.assertIn("Site_ID", keys)
        self.assertIn("Deprecated_Names", keys)
        self.assertIn("site_code", keys)

    # ── CSV / directory ──

    def test_load_directory_success(self):
        r = self._load_sample()
        self.assertTrue(r["ok"])
        self.assertEqual(r["site_count"], 3)

    def test_load_directory_empty(self):
        r = self.mgr.load_directory("", {})
        self.assertIn("error", r)

    def test_load_directory_bad_primary(self):
        r = self.mgr.load_directory(SAMPLE_CSV, {"primary": "Nope"})
        self.assertIn("error", r)

    def test_get_directory_before_load(self):
        r = self.mgr.get_directory()
        self.assertFalse(r["loaded"])

    def test_get_directory_after_load(self):
        self._load_sample()
        r = self.mgr.get_directory()
        self.assertTrue(r["loaded"])
        self.assertEqual(r["site_count"], 3)

    # ── Matching ──

    def test_match_exact(self):
        self._load_sample()
        self._make_folders("ACME-001", "ACME-002", "Unknown")
        r = self.mgr.match_folders(str(self.root))
        self.assertEqual(r["matched_count"], 2)
        by_folder = {m["folder"]: m for m in r["matches"]}
        self.assertEqual(by_folder["ACME-001"]["method"], "exact")
        self.assertEqual(by_folder["Unknown"]["method"], "unmatched")

    def test_match_contains_id(self):
        self._load_sample()
        self._make_folders("Site ACME-001 Extra")
        r = self.mgr.match_folders(str(self.root))
        by_folder = {m["folder"]: m for m in r["matches"]}
        self.assertEqual(by_folder["Site ACME-001 Extra"]["method"], "contains-id")

    def test_match_deprecated(self):
        self._load_sample()
        self._make_folders("Old Downtown")
        r = self.mgr.match_folders(str(self.root))
        by_folder = {m["folder"]: m for m in r["matches"]}
        self.assertEqual(by_folder["Old Downtown"]["method"], "deprecated")
        self.assertEqual(by_folder["Old Downtown"]["site_id"], "ACME-001")

    def test_match_address(self):
        self._load_sample()
        self._make_folders("123 Main St")
        r = self.mgr.match_folders(str(self.root))
        by_folder = {m["folder"]: m for m in r["matches"]}
        self.assertEqual(by_folder["123 Main St"]["method"], "address")

    # ── Folder rename (token-based) ──

    def test_preview_folder_rename_csv(self):
        self._load_sample()
        self._make_folders("ACME-001", "ACME-002")
        r = self.mgr.preview_folder_rename(
            str(self.root), "{Site_ID} - {Site_Name}")
        self.assertTrue(r["ok"])
        by_name = {x["current"]: x for x in r["renames"]}
        self.assertEqual(by_name["ACME-001"]["new_name"],
                         "ACME-001 - Downtown Office")
        self.assertEqual(by_name["ACME-001"]["status"], "rename")

    def test_preview_folder_rename_already_correct(self):
        self._load_sample()
        self._make_folders("ACME-001 - Downtown Office")
        r = self.mgr.preview_folder_rename(
            str(self.root), "{Site_ID} - {Site_Name}")
        by_name = {x["current"]: x for x in r["renames"]}
        self.assertEqual(
            by_name["ACME-001 - Downtown Office"]["status"], "already_correct")

    def test_preview_folder_rename_manual(self):
        self._make_folders("FolderA", "FolderB")
        r = self.mgr.preview_folder_rename(
            str(self.root), "{site_code} - {description}",
            separator=" - ",
            manual_values={"site_code": "ACME", "description": "HQ"})
        self.assertTrue(r["ok"])
        self.assertEqual(r["renames"][0]["new_name"], "ACME - HQ")

    def test_preview_folder_rename_manual_injects_folder(self):
        self._make_folders("Alpha", "Beta")
        r = self.mgr.preview_folder_rename(
            str(self.root), "{site_code} ({folder})",
            manual_values={"site_code": "ACME"})
        by_name = {x["current"]: x for x in r["renames"]}
        self.assertEqual(by_name["Alpha"]["new_name"], "ACME (Alpha)")
        self.assertEqual(by_name["Beta"]["new_name"], "ACME (Beta)")

    def test_execute_folder_rename(self):
        self._make_folders("OldName")
        renames = [{"current": "OldName", "new_name": "NewName"}]
        r = self.mgr.execute_folder_rename(str(self.root), renames)
        self.assertTrue(r["ok"])
        self.assertEqual(r["renamed"], 1)
        self.assertTrue((self.root / "NewName").is_dir())
        self.assertFalse((self.root / "OldName").exists())

    def test_execute_folder_rename_skips_same(self):
        self._make_folders("Same")
        r = self.mgr.execute_folder_rename(str(self.root),
                                            [{"current": "Same", "new_name": "Same"}])
        self.assertEqual(r["renamed"], 0)

    def test_execute_folder_rename_target_exists(self):
        self._make_folders("src", "dst")
        r = self.mgr.execute_folder_rename(str(self.root),
                                            [{"current": "src", "new_name": "dst"}])
        self.assertEqual(r["renamed"], 0)
        self.assertTrue(len(r["errors"]) > 0)

    # ── File rename (token-based) ──

    def test_preview_file_rename(self):
        self._load_sample()
        folder = self.root / "ACME-001"
        folder.mkdir()
        (folder / "survey.esx").write_text("fake")
        r = self.mgr.preview_file_rename(
            str(self.root), "{Site_ID} - {Site_Name}")
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["renames"]), 1)
        self.assertEqual(r["renames"][0]["new_name"],
                         "ACME-001 - Downtown Office.esx")

    def test_preview_file_rename_differentiates_files(self):
        self._load_sample()
        folder = self.root / "ACME-001"
        folder.mkdir()
        (folder / "a.esx").write_text("x")
        (folder / "b.esx").write_text("y")
        r = self.mgr.preview_file_rename(
            str(self.root), "{Site_ID} - {original}")
        names = [x["new_name"] for x in r["renames"]]
        self.assertEqual(len(set(names)), 2)
        self.assertIn("ACME-001 - a.esx", names)
        self.assertIn("ACME-001 - b.esx", names)

    def test_preview_file_rename_index_token(self):
        self._load_sample()
        folder = self.root / "ACME-001"
        folder.mkdir()
        (folder / "scan1.pdf").write_text("")
        (folder / "scan2.pdf").write_text("")
        r = self.mgr.preview_file_rename(
            str(self.root), "{Site_ID}_{index}")
        names = [x["new_name"] for x in r["renames"]]
        self.assertIn("ACME-001_1.pdf", names)
        self.assertIn("ACME-001_2.pdf", names)

    def test_execute_file_rename(self):
        folder = self.root / "SITE"
        folder.mkdir()
        (folder / "old.txt").write_text("data")
        renames = [{"folder": "SITE", "current": "old.txt", "new_name": "new.txt"}]
        r = self.mgr.execute_file_rename(str(self.root), renames)
        self.assertTrue(r["ok"])
        self.assertEqual(r["renamed"], 1)
        self.assertTrue((folder / "new.txt").exists())

    # ── Undo ──

    def test_undo_folders(self):
        self._make_folders("Original")
        self.mgr.execute_folder_rename(str(self.root),
                                        [{"current": "Original", "new_name": "Renamed"}])
        self.assertTrue((self.root / "Renamed").is_dir())
        r = self.mgr.undo_last("folders")
        self.assertTrue(r["ok"])
        self.assertEqual(r["reverted"], 1)
        self.assertTrue((self.root / "Original").is_dir())

    def test_undo_files(self):
        folder = self.root / "SITE"
        folder.mkdir()
        (folder / "old.txt").write_text("x")
        self.mgr.execute_file_rename(str(self.root),
                                      [{"folder": "SITE", "current": "old.txt",
                                        "new_name": "new.txt"}])
        r = self.mgr.undo_last("files")
        self.assertTrue(r["ok"])
        self.assertTrue((folder / "old.txt").exists())

    def test_undo_bulk(self):
        site = self.root / "SITE1"
        site.mkdir()
        (site / "OLD.txt").write_text("")
        items = [{"path": str(site / "OLD.txt"), "new_name": "new.txt"}]
        self.mgr.execute_bulk_rename(items)
        self.assertTrue((site / "new.txt").exists())
        r = self.mgr.undo_last("bulk")
        self.assertTrue(r["ok"])
        self.assertEqual(r["reverted"], 1)
        self.assertTrue((site / "OLD.txt").exists())

    def test_undo_no_log(self):
        r = self.mgr.undo_last("folders")
        self.assertIn("error", r)

    # ── Gap report ──

    def test_gap_report(self):
        self._load_sample()
        d1 = self.root / "ACME-001"
        d1.mkdir()
        (d1 / "project.esx").write_text("fake")
        d2 = self.root / "ACME-002"
        d2.mkdir()
        d3 = self.root / "Random"
        d3.mkdir()
        r = self.mgr.gap_report(str(self.root))
        self.assertTrue(r["ok"])
        self.assertEqual(len(r["has_data"]), 1)
        self.assertEqual(len(r["empty"]), 1)
        self.assertEqual(len(r["orphans"]), 1)
        self.assertEqual(len(r["not_started"]), 1)

    def test_gap_report_no_directory(self):
        r = self.mgr.gap_report(str(self.root))
        self.assertIn("error", r)

    # ── Profiles ──

    def test_save_and_list_profiles(self):
        self.mgr.save_profile("Standard", "{site_code} - {site_name}",
                               "{site_code}", " - ")
        r = self.mgr.list_profiles()
        self.assertIn("Standard", r["profiles"])
        p = r["profiles"]["Standard"]
        self.assertEqual(p["folder_format"], "{site_code} - {site_name}")
        self.assertEqual(p["file_format"], "{site_code}")

    def test_save_profile_with_file_rules(self):
        rules = {**DEFAULT_FILE_RULES, "case": "lower"}
        self.mgr.save_profile("WithRules", "", "", " - ", file_rules=rules)
        r = self.mgr.list_profiles()
        self.assertEqual(r["profiles"]["WithRules"]["file_rules"]["case"], "lower")

    def test_delete_profile(self):
        self.mgr.save_profile("Temp", "x", "y", "-")
        self.mgr.delete_profile("Temp")
        r = self.mgr.list_profiles()
        self.assertNotIn("Temp", r["profiles"])

    # ── Bulk rename (rule-based) ──

    def test_detect_rename_style(self):
        site = self.root / "SITE"
        site.mkdir()
        for name in ["file - one.txt", "file - two.txt", "file_three.txt"]:
            (site / name).write_text("")
        r = self.mgr.detect_rename_style(root=str(self.root))
        self.assertTrue(r["ok"])
        self.assertEqual(r["separator"], "spaced_hyphen")

    def test_preview_bulk_rename(self):
        site = self.root / "SITE1"
        site.mkdir()
        (site / "MyFile.txt").write_text("")
        rules = {**DEFAULT_FILE_RULES, "case": "lower"}
        r = self.mgr.preview_bulk_rename(
            root=str(self.root), rules=rules)
        self.assertTrue(r["ok"])
        self.assertEqual(r["count"], 1)
        self.assertEqual(r["items"][0]["new_name"], "myfile.txt")

    def test_execute_bulk_rename(self):
        site = self.root / "SITE1"
        site.mkdir()
        f = site / "OLD.txt"
        f.write_text("")
        items = [{"path": str(f), "new_name": "new.txt"}]
        r = self.mgr.execute_bulk_rename(items)
        self.assertTrue(r["ok"])
        self.assertEqual(r["renamed"], 1)
        self.assertTrue((site / "new.txt").exists())

    def test_execute_bulk_rename_target_exists(self):
        site = self.root / "SITE1"
        site.mkdir()
        (site / "a.txt").write_text("")
        (site / "b.txt").write_text("")
        items = [{"path": str(site / "a.txt"), "new_name": "b.txt"}]
        r = self.mgr.execute_bulk_rename(items)
        self.assertEqual(r["renamed"], 0)
        self.assertEqual(r["skipped"], 1)

    # ── CSV Helper ──

    def test_generate_csv_template_from_format(self):
        r = self.mgr.generate_csv_template("{site_code} - {city}")
        self.assertTrue(r["ok"])
        self.assertEqual(r["columns"][0], "site_code")
        self.assertEqual(r["columns"][1], "city")
        self.assertNotIn("date", r["columns"])
        self.assertNotIn("folder", r["columns"])

    def test_generate_csv_template_empty(self):
        r = self.mgr.generate_csv_template("")
        self.assertTrue(r["ok"])
        self.assertTrue(len(r["columns"]) > 0)

    def test_prefill_from_folders(self):
        self._make_folders("SiteA", "SiteB")
        r = self.mgr.prefill_from_folders(str(self.root))
        self.assertTrue(r["ok"])
        self.assertEqual(r["folder_count"], 2)
        self.assertIn("SiteA", r["csv_text"])
        self.assertIn("SiteB", r["csv_text"])

    def test_prefill_bad_root(self):
        r = self.mgr.prefill_from_folders("/nonexistent/path")
        self.assertIn("error", r)

    # ── Collision detection ──

    def test_collision_detected_in_folder_rename(self):
        self._load_sample()
        self._make_folders("ACME-001", "ACME-002")
        r = self.mgr.preview_folder_rename(str(self.root), "{City}")
        by_name = {x["current"]: x for x in r["renames"]}
        self.assertEqual(by_name["ACME-001"]["status"], "collision")
        self.assertEqual(by_name["ACME-002"]["status"], "collision")

    def test_no_collision_with_unique_names(self):
        self._load_sample()
        self._make_folders("ACME-001", "ACME-003")
        r = self.mgr.preview_folder_rename(str(self.root), "{Site_ID}")
        for entry in r["renames"]:
            self.assertNotEqual(entry["status"], "collision")

    # ── Legacy migration ──

    def test_legacy_profiles_migrated(self):
        old_path = self.state / "old_profiles.json"
        old_path.write_text(json.dumps({"Legacy": {"folder_format": "x"}}))
        mgr2 = RenameManager()
        r = mgr2.list_profiles()
        self.assertIn("Legacy", r["profiles"])
        new_path = self.state / "rename_profiles.json"
        self.assertTrue(new_path.exists())


class SettingsMigrationTests(unittest.TestCase):
    """Tests for settings.py rename-section migration."""

    def test_defaults_have_rename_section(self):
        self.assertIn("rename", DEFAULTS)
        self.assertIn("file_rules", DEFAULTS["rename"])
        self.assertEqual(DEFAULTS["rename"]["separator"], " - ")

    def test_load_settings_has_rename(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json",
                                         delete=False) as f:
            json.dump({}, f)
            path = f.name
        try:
            s = load_settings(_path=path)
            self.assertIn("rename", s)
            self.assertEqual(s["rename"]["folder_format"], "")
        finally:
            Path(path).unlink()

    def test_migrate_organizer_rename_to_rename_file_rules(self):
        settings = copy.deepcopy(DEFAULTS)
        settings["organizer"]["rename"] = {
            "strip_prefix": "IMG_",
            "case": "lower",
        }
        result = _migrate_settings(settings)
        self.assertEqual(result["rename"]["file_rules"]["strip_prefix"], "IMG_")
        self.assertEqual(result["rename"]["file_rules"]["case"], "lower")

    def test_no_overwrite_if_rename_file_rules_already_set(self):
        settings = copy.deepcopy(DEFAULTS)
        settings["organizer"]["rename"] = {"case": "lower"}
        settings["rename"]["file_rules"] = {
            **DEFAULT_FILE_RULES, "case": "upper"}
        result = _migrate_settings(settings)
        self.assertEqual(result["rename"]["file_rules"]["case"], "upper")

    def test_create_folder_template_token_migration(self):
        settings = copy.deepcopy(DEFAULTS)
        settings["organizer"]["create_folder_template"] = "{code} - {name} ({city})"
        result = _migrate_settings(settings)
        self.assertEqual(
            result["organizer"]["create_folder_template"],
            "{site_code} - {site_name} ({city})")

    def test_empty_template_unchanged(self):
        settings = copy.deepcopy(DEFAULTS)
        result = _migrate_settings(settings)
        self.assertEqual(result["organizer"]["create_folder_template"], "")


if __name__ == "__main__":
    unittest.main()
