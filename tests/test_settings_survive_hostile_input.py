"""A settings patch or an imported bundle cannot damage what it was not meant to.

Two faults, both found by running the real functions:

* `update_settings({"organizer": None})` replaced a whole section with `None`.
  `_migrate_settings` then called `.get` on it, so every later load - and the
  strict load inside every later save, the one that could have repaired it -
  raised `AttributeError`, and every page that read settings answered 500 until
  somebody edited the file by hand.
* `apply_import` wrote any bundle key that resolved inside the user directory
  and refused the credential files by exact spelling. NTFS reads `Cookies.json`
  and `cookies.json` as one file, and `cookies.json` is the legacy file
  `load_cookies_from_disk` migrates into the encrypted session store.

Each test drives the real function against a throwaway directory.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import settings, settings_backup


class SettingsStayWellFormedTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "settings.json"

    def test_a_patch_that_replaces_a_section_with_a_value_is_refused(self):
        settings.update_settings({"global": {"output_dir": "x"}}, _path=self.path)
        before = self.path.read_bytes()
        for bad in (None, 5, "text", [1]):
            with self.assertRaises(ValueError):
                settings.update_settings({"organizer": bad}, _path=self.path)
        self.assertEqual(self.path.read_bytes(), before,
                         "a refused patch must not touch the file")
        # ...and settings still load and save afterwards.
        merged = settings.update_settings({"global": {"output_dir": "y"}},
                                          _path=self.path)
        self.assertEqual(merged["global"]["output_dir"], "y")

    def test_a_nested_section_is_checked_too(self):
        with self.assertRaises(ValueError) as ctx:
            settings.update_settings({"global": {"subfolder_names": None}},
                                     _path=self.path)
        self.assertIn("global.subfolder_names", str(ctx.exception))

    def test_a_file_already_in_that_state_heals_on_load(self):
        self.path.write_text(json.dumps(
            {"organizer": None, "global": {"output_dir": "kept"}, "rename": 3}),
            encoding="utf-8")
        loaded = settings.load_settings(_path=self.path, strict=True)
        self.assertIsInstance(loaded["organizer"], dict)
        self.assertIsInstance(loaded["rename"], dict)
        self.assertEqual(loaded["global"]["output_dir"], "kept",
                         "a healthy section keeps what was saved")
        # The save that used to fail now works and writes a well-formed file.
        settings.update_settings({"global": {"output_dir": "z"}}, _path=self.path)
        on_disk = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertIsInstance(on_disk["organizer"], dict)

    def test_ordinary_patches_still_merge(self):
        merged = settings.update_settings(
            {"global": {"output_dir": "a"}, "walls": {"units": "metric"}},
            _path=self.path)
        self.assertEqual(merged["walls"]["units"], "metric")
        self.assertEqual(merged["global"]["output_dir"], "a")


class ImportOnlyWritesWhatAnExportWritesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        p = patch.object(settings, "SETTINGS_FILE", self.root / "settings.json")
        p.start()
        self.addCleanup(p.stop)

    def _apply(self, files):
        bundle = {"schema": settings_backup.SCHEMA_VERSION, "files":
                  {k: {"text": "{}"} for k in files}}
        return settings_backup.apply_import(
            bundle, sections=("files",), root=self.root)["applied"]

    def test_credential_files_are_refused_whatever_the_spelling(self):
        names = ["cookies.json", "Cookies.json", "COOKIES.JSON", "cookies.json.",
                 "cookies.json ", "cookies.enc", "Cookies.ENC",
                 "templates/cookies.json", "templates/Cookies.enc"]
        result = self._apply(names)
        self.assertEqual(result["files"], [])
        self.assertEqual(sorted(result["refused"]), sorted(names))
        for n in ("cookies.json", "Cookies.json", "cookies.enc"):
            self.assertFalse((self.root / n).exists(), n)

    def test_importable_name_answers_each_key_directly(self):
        name = settings_backup.importable_name
        self.assertIsNone(name("Cookies.json"))
        self.assertIsNone(name("cookies.json."))
        self.assertIsNone(name("templates/../hidden.json"))
        self.assertIsNone(name(None))
        self.assertEqual("config.json", name("CONFIG.json"))
        self.assertEqual("templates/a/b.json", name("Templates/a/b.json"))

    def test_files_an_export_never_writes_are_refused(self):
        names = ["hidden.json", "logs/anything.txt", "settings-backups/x.json",
                 "templates/../hidden.json", "/abs.json", "C:/x.json",
                 "templates/.migrated", "stream:name.json"]
        result = self._apply(names)
        self.assertEqual(result["files"], [])
        self.assertEqual(len(result["refused"]), len(names))
        self.assertFalse((self.root / "hidden.json").exists())
        self.assertFalse((self.root / "logs").exists())

    def test_what_an_export_writes_is_still_imported(self):
        result = self._apply(["config.json", "share_recipients.json",
                              "templates/mine.json", "capacity/x.json"])
        self.assertEqual(sorted(result["files"]),
                         ["capacity/x.json", "config.json",
                          "share_recipients.json", "templates/mine.json"])
        self.assertTrue((self.root / "templates" / "mine.json").is_file())

    def test_a_case_variant_of_an_allowed_name_lands_under_the_real_name(self):
        result = self._apply(["Config.JSON", "Templates/Mine.json"])
        self.assertEqual(sorted(result["files"]),
                         ["config.json", "templates/Mine.json"])

    def test_the_write_is_atomic_and_leaves_no_temp_file(self):
        self._apply(["config.json"])
        leftovers = [p.name for p in self.root.rglob("*.wd-import.tmp")]
        self.assertEqual(leftovers, [])

    def test_the_preview_names_what_would_be_refused(self):
        bundle = {"schema": settings_backup.SCHEMA_VERSION, "files": {
            "Cookies.json": {"text": "{}"}, "config.json": {"text": "{}"}}}
        pre = settings_backup.preview_import(bundle, root=self.root)
        self.assertEqual([r["key"] for r in pre["files"]["refused"]],
                         ["Cookies.json"])
        self.assertEqual([r["key"] for r in pre["files"]["add"]], ["config.json"])

    def test_an_import_takes_a_full_export_first(self):
        (self.root / "config.json").write_text('{"a": 1}', encoding="utf-8")
        self._apply(["config.json"])
        dumps = list((self.root / settings_backup.AUTO_DIR_NAME).glob(
            "settings-import*.json"))
        if settings_backup.KEEP_COPIES > 0:
            self.assertTrue(dumps, "no export was taken before the import")


if __name__ == "__main__":
    unittest.main()
