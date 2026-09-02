from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import tools.template_store as template_module
from tools.template_store import TemplateStore

SUFFIX = "_walltemplate.json"


class TemplateStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.folder = root / "user"
        self.builtin = root / "builtin"
        self.builtin.mkdir(parents=True)
        self.defaults = self.builtin / "ekahau_defaults.json"
        self.patchers = [
            patch.object(template_module, "USER_DIR", self.folder),
            patch.object(template_module, "BUILTIN_DIR", self.builtin),
            patch.object(template_module, "DEFAULTS_FILE", self.defaults),
        ]
        for p in self.patchers:
            p.start()
        self.store = TemplateStore()

    def tearDown(self):
        for p in reversed(self.patchers):
            p.stop()
        self.temp.cleanup()

    def _write_builtin(self, name, walls):
        path = self.builtin / f"{name}{SUFFIX}"
        path.write_text(json.dumps({"name": name, "wallTypes": walls}), encoding="utf-8")
        return path

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
        (self.folder / ".migrated").write_text("", encoding="utf-8")
        self.defaults.write_text(json.dumps({"wallTypes": [{"name": "Default"}]}), encoding="utf-8")
        (self.folder / "invalid.json").write_text("not json", encoding="utf-8")
        self.assertEqual(self.store.get_defaults()["wallTypes"][0]["name"], "Default")
        self.assertEqual(self.store.scan()["templates"], [])

    def test_saves_never_touch_the_install_tree(self):
        """The whole point of the split: an update can replace templates/ safely."""
        before = sorted(p.name for p in self.builtin.iterdir())
        self.store.save("Anything", [{"name": "W"}])
        self.store.delete(f"Anything{SUFFIX}")
        self.assertEqual(sorted(p.name for p in self.builtin.iterdir()), before)

    def test_builtin_is_listed_and_marked(self):
        self._write_builtin("Shipped", [{"name": "Brick"}])
        templates = self.store.scan()["templates"]
        self.assertEqual(len(templates), 1)
        self.assertEqual(templates[0]["name"], "Shipped")
        self.assertTrue(templates[0]["builtin"])

    def test_user_copy_shadows_builtin_without_editing_it(self):
        builtin_path = self._write_builtin("Shipped", [{"name": "Brick"}])
        self.store.scan()  # trigger migration first
        self.store.save("Shipped", [{"name": "Mine"}])

        templates = self.store.scan()["templates"]
        self.assertEqual(len(templates), 1, "user copy should shadow, not duplicate")
        self.assertEqual(templates[0]["wallTypes"], [{"name": "Mine"}])
        self.assertFalse(templates[0]["builtin"])

        shipped = json.loads(builtin_path.read_text(encoding="utf-8"))
        self.assertEqual(shipped["wallTypes"], [{"name": "Brick"}])

    def test_deleting_a_builtin_tombstones_instead_of_removing(self):
        builtin_path = self._write_builtin("Shipped", [{"name": "Brick"}])
        self.store.scan()
        deleted = self.store.delete(f"Shipped{SUFFIX}")
        self.assertTrue(deleted["ok"])
        self.assertTrue(builtin_path.is_file(), "shipped file must survive")
        self.assertEqual(self.store.scan()["templates"], [])

    def test_reset_restores_the_builtin(self):
        self._write_builtin("Shipped", [{"name": "Brick"}])
        self.store.scan()
        self.store.save("Shipped", [{"name": "Mine"}])
        result = self.store.reset(f"Shipped{SUFFIX}")
        self.assertTrue(result["ok"])
        templates = self.store.scan()["templates"]
        self.assertEqual(templates[0]["wallTypes"], [{"name": "Brick"}])
        self.assertTrue(templates[0]["builtin"])

    def test_reset_undoes_a_tombstone(self):
        self._write_builtin("Shipped", [{"name": "Brick"}])
        self.store.scan()
        self.store.delete(f"Shipped{SUFFIX}")
        self.assertEqual(self.store.scan()["templates"], [])
        self.store.reset(f"Shipped{SUFFIX}")
        self.assertEqual(len(self.store.scan()["templates"]), 1)

    def test_saving_over_a_tombstoned_builtin_makes_it_visible_again(self):
        self._write_builtin("Shipped", [{"name": "Brick"}])
        self.store.scan()
        self.store.delete(f"Shipped{SUFFIX}")
        self.store.save("Shipped", [{"name": "Mine"}])
        templates = self.store.scan()["templates"]
        self.assertEqual(len(templates), 1)
        self.assertEqual(templates[0]["wallTypes"], [{"name": "Mine"}])

    def test_migration_leaves_shipped_templates_as_builtins(self):
        """Copying shipped names would freeze a private duplicate and cut the
        user off from upstream template updates."""
        self._write_builtin("WD Template", [{"name": "Shipped"}])
        result = template_module.migrate_legacy_templates()
        self.assertEqual(result["migrated"], [])
        self.assertFalse((self.folder / f"WD Template{SUFFIX}").exists())
        templates = self.store.scan()["templates"]
        self.assertTrue(templates[0]["builtin"])

    def test_migration_relocates_user_created_templates_once(self):
        self._write_builtin("WD Template", [{"name": "Shipped"}])
        stray = self.builtin / f"My Site{SUFFIX}"
        stray.write_text(json.dumps({"name": "My Site", "wallTypes": [{"name": "Mine"}]}),
                         encoding="utf-8")

        with patch.object(template_module, "builtin_names",
                          return_value={f"WD Template{SUFFIX}"}):
            result = template_module.migrate_legacy_templates()
            self.assertFalse(result["already"])
            self.assertEqual(result["migrated"], [f"My Site{SUFFIX}"])
            self.assertTrue((self.folder / f"My Site{SUFFIX}").is_file())

            again = template_module.migrate_legacy_templates()
            self.assertTrue(again["already"])
            self.assertEqual(again["migrated"], [])

    def test_migration_never_overwrites_an_existing_user_file(self):
        stray = self.builtin / f"My Site{SUFFIX}"
        stray.write_text(json.dumps({"name": "My Site", "wallTypes": [{"name": "Old"}]}),
                         encoding="utf-8")
        self.folder.mkdir(parents=True)
        mine = self.folder / f"My Site{SUFFIX}"
        mine.write_text(json.dumps({"name": "My Site", "wallTypes": [{"name": "Mine"}]}),
                        encoding="utf-8")
        with patch.object(template_module, "builtin_names", return_value=set()):
            template_module.migrate_legacy_templates()
        kept = json.loads(mine.read_text(encoding="utf-8"))
        self.assertEqual(kept["wallTypes"], [{"name": "Mine"}])

    def test_rescue_dirty_builtin_preserves_an_in_place_edit(self):
        """The updater's escape hatch for a tracked template the user edited."""
        self._write_builtin("WD Template", [{"name": "Edited In Place"}])
        result = template_module.rescue_dirty_builtin(f"WD Template{SUFFIX}")
        self.assertTrue(result["ok"])
        self.assertTrue(result["rescued"])
        saved = json.loads((self.folder / f"WD Template{SUFFIX}").read_text(encoding="utf-8"))
        self.assertEqual(saved["wallTypes"], [{"name": "Edited In Place"}])

    def test_rescue_does_not_clobber_an_existing_user_copy(self):
        self._write_builtin("WD Template", [{"name": "Shipped"}])
        self.folder.mkdir(parents=True)
        mine = self.folder / f"WD Template{SUFFIX}"
        mine.write_text(json.dumps({"name": "WD Template", "wallTypes": [{"name": "Mine"}]}),
                        encoding="utf-8")
        result = template_module.rescue_dirty_builtin(f"WD Template{SUFFIX}")
        self.assertTrue(result["ok"])
        self.assertFalse(result["rescued"])
        kept = json.loads(mine.read_text(encoding="utf-8"))
        self.assertEqual(kept["wallTypes"], [{"name": "Mine"}])


if __name__ == "__main__":
    unittest.main()
