from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools.template_store as template_module
from tools.template_store import TemplateStore


class TemplateStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name) / "templates"
        self.defaults = self.folder / "ekahau_defaults.json"
        self.patchers = [
            patch.object(template_module, "TPL_DIR", self.folder),
            patch.object(template_module, "DEFAULTS_FILE", self.defaults),
        ]
        for p in self.patchers:
            p.start()
        self.store = TemplateStore()

    def tearDown(self):
        for p in reversed(self.patchers):
            p.stop()
        self.temp.cleanup()

    def test_save_scan_and_delete(self):
        walls = [{"name": "Sample Wall", "attenuation": 5}]
        saved = self.store.save("My / Template", walls)
        self.assertTrue(saved["ok"])
        self.assertNotIn("/", saved["file"])
        scanned = self.store.scan()
        self.assertEqual(len(scanned["templates"]), 1)
        self.assertEqual(scanned["templates"][0]["wallTypes"], walls)
        deleted = self.store.delete(saved["file"])
        self.assertTrue(deleted["ok"])
        self.assertEqual(self.store.scan()["templates"], [])

    def test_delete_rejects_path_traversal(self):
        self.folder.mkdir()
        outside = self.folder.parent / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        result = self.store.delete("../outside.json")
        self.assertFalse(result["ok"])
        self.assertTrue(outside.exists())

    def test_defaults_and_invalid_templates(self):
        self.folder.mkdir()
        self.defaults.write_text(json.dumps({"wallTypes": [{"name": "Default"}]}), encoding="utf-8")
        (self.folder / "invalid.json").write_text("not json", encoding="utf-8")
        self.assertEqual(self.store.get_defaults()["wallTypes"][0]["name"], "Default")
        self.assertEqual(self.store.scan()["templates"], [])


if __name__ == "__main__":
    unittest.main()
