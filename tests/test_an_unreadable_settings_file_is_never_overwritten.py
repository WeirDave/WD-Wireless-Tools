"""A settings.json that cannot be read is refused, never replaced with defaults.

`load_settings` swallowed every parse error and returned the defaults. With
`setup_complete` reading False the app sent him to Setup, and the next save of
any preference anywhere wrote the defaults over his file. A UTF-8 byte-order
mark - what Notepad writes - was enough to lose every setting.

Now a BOM is read like any other UTF-8, and a file that really cannot be read
is left exactly as it is: writes raise an error that names it, the failure is
logged, and Setup is not offered. Importing a settings backup is still the way
back, because the import copies the damaged file aside first.
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tools import settings, settings_backup

MINE = {"setup_complete": True,
        "global": {"output_dir": "D:/Invented/Projects"},
        "report": {"prepared_by": "Example Person"}}

DAMAGED = {
    "truncated": b'{"setup_complete": true, "global": {"output_dir": "D:/Inv',
    "not an object": b'["setup_complete", true]',
    "not utf-8": b'{"setup_complete": true, "x": "\xff\xfe"}',
}


class _Harness(unittest.TestCase):

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.file = self.root / "settings.json"
        for name, value in (("SETTINGS_FILE", self.file),
                            ("SETTINGS_DIR", self.root)):
            p = mock.patch.object(settings, name, value)
            p.start()
            self.addCleanup(p.stop)


class AByteOrderMarkIsReadTests(_Harness):

    def test_a_file_saved_with_a_bom_keeps_every_value(self):
        self.file.write_bytes(b"\xef\xbb\xbf" + json.dumps(MINE).encode("utf-8"))

        self.assertFalse(settings.needs_setup())
        settings.update_settings({"walls": {"units": "imperial"}})

        after = json.loads(self.file.read_bytes().decode("utf-8-sig"))
        self.assertEqual(after["global"]["output_dir"], "D:/Invented/Projects")
        self.assertEqual(after["report"]["prepared_by"], "Example Person")
        self.assertTrue(after["setup_complete"])
        self.assertEqual(after["walls"]["units"], "imperial")


class ADamagedFileIsLeftAloneTests(_Harness):

    def test_a_save_is_refused_and_the_file_is_untouched(self):
        for name, raw in DAMAGED.items():
            with self.subTest(name):
                self.file.write_bytes(raw)
                with self.assertLogs("wd", "ERROR"), \
                        self.assertRaises(settings.SettingsUnreadable) as ctx:
                    settings.update_settings({"walls": {"units": "imperial"}})
                self.assertEqual(self.file.read_bytes(), raw)
                # It names the file, so he can find it.
                self.assertTrue(str(self.file) in str(ctx.exception))

    def test_setup_is_not_offered(self):
        with self.assertLogs("wd", "ERROR"):
            for name, raw in DAMAGED.items():
                with self.subTest(name):
                    self.file.write_bytes(raw)
                    self.assertFalse(settings.needs_setup())

    def test_settings_unreadable_names_the_problem_only_when_there_is_one(self):
        self.assertIsNone(settings.settings_unreadable())          # no file
        self.file.write_text(json.dumps(MINE), encoding="utf-8")
        self.assertIsNone(settings.settings_unreadable())          # readable
        self.file.write_bytes(DAMAGED["not an object"])
        with self.assertLogs("wd", "ERROR"):
            problem = settings.settings_unreadable()
        self.assertTrue(str(self.file) in problem)

    def test_a_missing_file_still_means_setup(self):
        self.assertTrue(settings.needs_setup())

    def test_the_page_is_told_in_words_and_nothing_is_written(self):
        import server
        raw = DAMAGED["truncated"]
        self.file.write_bytes(raw)
        client = server.app.test_client()
        with self.assertLogs("wd", "ERROR"):
            resp = client.post("/api/settings/update",
                               json={"patch": {"walls": {"units": "imperial"}}},
                               headers={"X-WD-Wireless-Tools": "1"})
        body = resp.get_json()
        self.assertFalse(body.get("ok", False))
        self.assertTrue(str(self.file) in body["error"])
        self.assertEqual(self.file.read_bytes(), raw)

    def test_an_export_does_not_pass_the_defaults_off_as_his(self):
        self.file.write_bytes(DAMAGED["truncated"])
        with self.assertLogs("wd", "ERROR"), \
                self.assertRaises(settings.SettingsUnreadable):
            settings_backup.export_bundle(root=self.root)


class AnImportIsTheWayBackTests(_Harness):

    def test_an_import_replaces_a_damaged_file_after_copying_it_aside(self):
        raw = DAMAGED["truncated"]
        self.file.write_bytes(raw)
        bundle = {"settings": copy.deepcopy(MINE)}

        with self.assertLogs("wd", "ERROR"):
            settings_backup.apply_import(bundle, sections=("settings",),
                                         root=self.root)

        after = json.loads(self.file.read_text(encoding="utf-8"))
        self.assertEqual(after["global"]["output_dir"], "D:/Invented/Projects")
        copies = [p for p in self.root.iterdir()
                  if p.name.startswith("settings.backup-")]
        self.assertEqual(len(copies), 1)
        self.assertEqual(copies[0].read_bytes(), raw)

    def test_an_import_over_a_readable_file_still_merges(self):
        self.file.write_text(json.dumps(MINE), encoding="utf-8")
        settings_backup.apply_import(
            {"settings": {"walls": {"units": "imperial"}}},
            sections=("settings",), root=self.root)
        after = json.loads(self.file.read_text(encoding="utf-8"))
        self.assertEqual(after["walls"]["units"], "imperial")
        self.assertEqual(after["report"]["prepared_by"], "Example Person")


if __name__ == "__main__":
    unittest.main()
