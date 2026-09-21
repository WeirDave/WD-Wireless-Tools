"""`settings.migrate_legacy` runs at startup and nothing had ever run it.

Backlog item 12: 30 public functions in `tools/` that no test so much as
mentions. This is one of the two a browser can reach - `server.py` calls it on
the way up - and it is the one whose failure is hardest to notice, because a
migration that drops a key does not raise. It writes a settings file that looks
complete and is missing the thing somebody configured.

**What it is for.** Settings used to live in two per-module files,
`organizer_config.json` and `config.json`. `settings.json` replaced both. This
carries the old values across on the first run after an upgrade, once, and
leaves the legacy files in place as inert copies.

Three properties matter and only one of them is obvious:

* **It is idempotent.** If `settings.json` exists it returns that and touches
  nothing. Re-running the migration over a configured install would otherwise
  reset it to defaults - and it runs on *every* startup, so this is the
  property the whole design rests on.
* **A key goes to the right half of the schema.** `subfolders` and its two
  companions are global; everything else in the organizer file is the
  organizer's. Sending one to the wrong half loses it silently, because
  `load_settings` reads a schema where the value is simply absent.
* **A corrupt legacy file must not stop the migration.** Both reads are inside
  a bare `except`, deliberately: half a migration beats refusing to start.

Nothing here touches the real user directory. `tests/__init__.py` sets
`WD_USER_DIR` before any import, and every test below additionally patches the
three module constants at their own temp directory, because the module reads
them once at import and they are what the function actually opens.
"""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import settings


class MigrateLegacyTests(unittest.TestCase):

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-migrate-"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.settings_file = self.tmp / "settings.json"
        self.organizer = self.tmp / "organizer_config.json"
        self.cloud = self.tmp / "config.json"
        for name, value in (("SETTINGS_FILE", self.settings_file),
                            ("LEGACY_ORGANIZER_CONFIG", self.organizer),
                            ("LEGACY_CLOUD_CONFIG", self.cloud)):
            patcher = mock.patch.object(settings, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def write(self, path: Path, data: dict):
        path.write_text(json.dumps(data), encoding="utf-8")

    def on_disk(self) -> dict:
        return json.loads(self.settings_file.read_text(encoding="utf-8"))

    # -- the property the design rests on ------------------------------------

    def test_an_existing_settings_file_is_returned_untouched(self):
        """It runs on every startup, so this is what stops it resetting.

        Not just "returns the same dict" - the file must not be rewritten
        either, because a rewrite would drop any key this schema does not
        know about.
        """
        mine = {"_version": 1, "setup_complete": True,
                "global": {"output_dir": "D:/Projects"},
                "something_a_later_version_added": 42}
        self.write(self.settings_file, mine)
        before = self.settings_file.read_bytes()

        result = settings.migrate_legacy()

        self.assertEqual("D:/Projects", result["global"]["output_dir"])
        self.assertEqual(before, self.settings_file.read_bytes(),
                         "the settings file was rewritten by a migration that "
                         "should have returned it untouched")

    def test_running_it_twice_changes_nothing_the_second_time(self):
        self.write(self.organizer, {"create_folder_template": "{site}-{floor}"})
        first = settings.migrate_legacy()
        after_first = self.settings_file.read_bytes()

        second = settings.migrate_legacy()

        self.assertEqual(first["organizer"]["create_folder_template"],
                         second["organizer"]["create_folder_template"])
        self.assertEqual(after_first, self.settings_file.read_bytes())

    # -- the keys land in the right half ------------------------------------

    def test_the_three_global_keys_go_to_global(self):
        """`subfolders` and its two companions are shared, not the organizer's.

        They are named in `_GLOBAL_KEYS` for this reason. Put one in
        `organizer` and `load_settings` reads a schema where it is absent, so
        the value is gone with nothing raised.
        """
        self.write(self.organizer, {
            "subfolders": ["plans", "photos"],
            "subfolder_names": {"plans": "Plans", "photos": "Photos"},
            "custom_destinations": [{"name": "Surveys", "ext": [".esx"]}],
        })
        result = settings.migrate_legacy()

        self.assertEqual(["plans", "photos"], result["global"]["subfolders"])
        self.assertEqual({"plans": "Plans", "photos": "Photos"},
                         result["global"]["subfolder_names"])
        self.assertEqual([{"name": "Surveys", "ext": [".esx"]}],
                         result["global"]["custom_destinations"])
        for key in ("subfolders", "subfolder_names", "custom_destinations"):
            with self.subTest(key=key):
                self.assertNotIn(key, result["organizer"],
                                 "a global key was copied into organizer too")

    def test_everything_else_in_the_organizer_file_stays_the_organizer_s(self):
        self.write(self.organizer, {
            "create_folder_template": "{site} {floor}",
            "skip_dirs": ["archive"],
            "report_keywords": ["survey"],
        })
        result = settings.migrate_legacy()

        self.assertEqual("{site} {floor}",
                         result["organizer"]["create_folder_template"])
        self.assertEqual(["archive"], result["organizer"]["skip_dirs"])
        self.assertEqual(["survey"], result["organizer"]["report_keywords"])

    def test_a_key_the_schema_does_not_know_is_dropped_rather_than_kept(self):
        """Deliberate, and worth pinning so nobody "fixes" it by accident.

        The migration only copies a key it already has a home for. A stray key
        from an older build would otherwise sit in the new file forever,
        looking like a setting that does something.
        """
        self.write(self.organizer, {"an_option_that_no_longer_exists": True})
        result = settings.migrate_legacy()
        self.assertNotIn("an_option_that_no_longer_exists", result["organizer"])
        self.assertNotIn("an_option_that_no_longer_exists", result["global"])

    def test_the_cloud_output_directory_is_carried_across(self):
        self.write(self.cloud, {"output_dir": "E:/Ekahau"})
        result = settings.migrate_legacy()
        self.assertEqual("E:/Ekahau", result["global"]["output_dir"])

    def test_an_empty_cloud_output_directory_does_not_overwrite_anything(self):
        """`if cloud.get("output_dir")` - falsy, so the default survives."""
        self.write(self.cloud, {"output_dir": ""})
        result = settings.migrate_legacy()
        self.assertEqual(settings.DEFAULTS["global"]["output_dir"],
                         result["global"]["output_dir"])

    # -- and it has to survive a bad file -----------------------------------

    def test_a_corrupt_organizer_file_does_not_stop_the_migration(self):
        """Half a migration beats refusing to start.

        Both reads sit inside a bare `except` on purpose. The cloud file is
        read afterwards, so the assertion that matters is that it still was.
        """
        self.organizer.write_text("{ this is not json", encoding="utf-8")
        self.write(self.cloud, {"output_dir": "F:/Work"})

        result = settings.migrate_legacy()

        self.assertTrue(result["setup_complete"])
        self.assertEqual("F:/Work", result["global"]["output_dir"],
                         "a corrupt organizer file stopped the cloud file "
                         "being read")

    def test_a_corrupt_cloud_file_does_not_stop_the_migration(self):
        self.write(self.organizer, {"skip_dirs": ["tmp"]})
        self.cloud.write_text("\x00\x01 not json either", encoding="utf-8")

        result = settings.migrate_legacy()

        self.assertEqual(["tmp"], result["organizer"]["skip_dirs"])

    def test_no_legacy_files_at_all_still_produces_a_usable_file(self):
        """A fresh install that has never had either file.

        `setup_complete` is True even here, which is worth knowing: this
        function is only called where the app has decided a migration is what
        is wanted, and it says so in its own docstring - an existing user has
        already been using the app.
        """
        result = settings.migrate_legacy()
        self.assertTrue(self.settings_file.is_file())
        self.assertTrue(result["setup_complete"])
        self.assertEqual(settings.DEFAULTS["organizer"]["image_ext"],
                         result["organizer"]["image_ext"])

    def test_what_is_returned_is_what_was_written(self):
        """Otherwise the caller acts on one thing and the next start reads
        another."""
        self.write(self.organizer, {"subfolders": ["a"], "skip_dirs": ["b"]})
        returned = settings.migrate_legacy()
        self.assertEqual(returned, self.on_disk())

    def test_the_legacy_files_are_left_where_they_were(self):
        """Named in the docstring as inert backups, so nothing deletes them."""
        self.write(self.organizer, {"skip_dirs": ["x"]})
        self.write(self.cloud, {"output_dir": "G:/y"})
        settings.migrate_legacy()
        self.assertTrue(self.organizer.is_file())
        self.assertTrue(self.cloud.is_file())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
