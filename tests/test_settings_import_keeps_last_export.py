"""Importing a settings export does not turn "Last exported" back.

The export route builds the bundle and only then stamps the time, so the
bundle carries the *previous* export's time. Importing it - on this machine to
undo a mistake, or on another to carry settings across - wrote that older time
over the real one, and Settings then reported the last export as older than
it was, or as never. "Last exported" is a fact about this machine, so an import
leaves it alone, and the preview does not list it as a change.

Driven through the real routes with Flask's test client, in a throwaway user
directory.
"""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import server  # noqa: E402
from tools import settings  # noqa: E402

HDR = {"X-WD-Wireless-Tools": "1"}


class LastExportedSurvivesAnImport(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        p = patch.object(settings, "SETTINGS_FILE", Path(self.tmp.name) / "settings.json")
        p.start()
        self.addCleanup(p.stop)
        settings.save_settings(settings.load_settings())
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()

    def post(self, action, body):
        return self.client.post("/api/settings/" + action, json=body, headers=HDR).get_json()

    def last_export(self):
        return self.post("get", {})["settings"]["global"]["last_settings_export"]

    def test_importing_the_export_just_taken_keeps_its_time(self):
        ex = self.post("export", {})
        self.assertTrue(ex["takenAt"])
        self.assertEqual(self.last_export(), ex["takenAt"])
        r = self.post("import_apply", {"bundle": ex["bundle"], "sections": ["settings"]})
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.last_export(), ex["takenAt"])

    def test_the_rest_of_the_settings_still_come_back(self):
        """Ignoring one key is not ignoring the section."""
        ex = self.post("export", {})
        units = ex["bundle"]["settings"]["report"]["units"]
        other = "meters" if units != "meters" else "feet"
        self.post("update", {"patch": {"report": {"units": other}}})
        self.post("import_apply", {"bundle": ex["bundle"], "sections": ["settings"]})
        self.assertEqual(self.post("get", {})["settings"]["report"]["units"], units)

    def test_the_preview_does_not_offer_it_as_a_change(self):
        ex = self.post("export", {})
        pv = self.post("import_preview", {"bundle": ex["bundle"]})
        keys = [row["key"] for block in pv["settings"].values() for row in block]
        self.assertNotIn("global.last_settings_export", keys)


if __name__ == "__main__":
    unittest.main()
