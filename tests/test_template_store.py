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

    def test_a_template_we_do_not_ship_is_treated_as_the_users_own(self):
        """`templates/` holding something off the manifest means user work.

        It is listed once and relocated into the user folder, which is the
        whole point of the migration - the install tree has to stay disposable.
        """
        self._write_builtin("Shipped", [{"name": "Brick"}])
        templates = self.store.scan()["templates"]
        self.assertEqual(len(templates), 1)
        self.assertEqual(templates[0]["name"], "Shipped")
        self.assertFalse(templates[0]["builtin"])
        self.assertTrue((self.folder / f"Shipped{SUFFIX}").is_file())

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

    def test_shipped_templates_become_the_users_own_copy(self):
        """This reverses an earlier decision, deliberately. Read before undoing.

        The rule used to be that shipped names are never copied, because a
        private duplicate cuts the user off from upstream template
        improvements. That is a real cost and it was the wrong side of the
        trade. The consequence was that his wall template was never his: his
        three recoloured types and his nine keyboard shortcuts lived only in
        the repository's own tracked file, so a commit on 14 September replaced
        his colours with Ekahau's greys and he lost his template without
        anything being deleted.

        A template the project owns is a template the project overwrites. So
        the shipped set is seeded into the user folder and shadowed from there.
        """
        self._write_builtin("WD Template", [{"name": "Shipped"}])
        template_module.migrate_legacy_templates()
        self.assertEqual(template_module.seed_user_templates()["seeded"],
                         [f"WD Template{SUFFIX}"])
        self.assertTrue((self.folder / f"WD Template{SUFFIX}").is_file())
        templates = self.store.scan()["templates"]
        self.assertEqual(len(templates), 1, "seeding must shadow, not duplicate")
        self.assertFalse(templates[0]["builtin"])

    def test_seeding_never_overwrites_what_is_already_his(self):
        self._write_builtin("WD Template", [{"name": "Shipped"}])
        mine = self.folder / f"WD Template{SUFFIX}"
        self.folder.mkdir(parents=True, exist_ok=True)
        mine.write_text(json.dumps({"name": "WD Template",
                                    "wallTypes": [{"name": "My calibration"}]}),
                        encoding="utf-8")
        self.assertEqual(template_module.seed_user_templates()["seeded"], [])
        self.assertEqual(json.loads(mine.read_text(encoding="utf-8"))["wallTypes"],
                         [{"name": "My calibration"}])

    def test_seeding_does_not_resurrect_one_he_deleted(self):
        """A tombstone is a decision, and seeding must not overrule it."""
        self._write_builtin("WD Template", [{"name": "Shipped"}])
        self.store.scan()
        self.store.delete(f"WD Template{SUFFIX}")
        self.assertEqual(self.store.scan()["templates"], [])
        self.assertEqual(template_module.seed_user_templates()["seeded"], [])
        self.assertEqual(self.store.scan()["templates"], [])

    def test_migration_relocates_user_created_templates_once(self):
        """Runs the real `builtin_names()`. That is the point of this test.

        It used to patch `builtin_names` out and hand the migration a fixed
        set - which is why fifteen green tests sat on top of a migration that
        could never migrate anything. The real function listed the directory
        it was about to walk, so "skip what we ship" skipped every file;
        mocking it was the only reason this test passed. A mock of the
        function under test is a hole in exactly the shape of the bug.
        """
        self._write_builtin("WD Template", [{"name": "Shipped"}])
        stray = self.builtin / f"My Site{SUFFIX}"
        stray.write_text(json.dumps({"name": "My Site", "wallTypes": [{"name": "Mine"}]}),
                         encoding="utf-8")

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


class TheTwoTemplatesWeActuallyShip(unittest.TestCase):
    """Against the real files in `templates/`, not fixtures.

    Every test above this one builds its own templates in a temp directory, so
    all of them stayed green through the release that replaced his three wall
    colours with Ekahau's greys. Nothing asserted anything about the file we
    actually ship. This does.

    He asked for two, in these words: "we should have both the default Ekahau
    template and the WD recommendations." Ekahau Default is the baseline he can
    return to; WD Template is the curated set.
    """

    ROOT = Path(__file__).resolve().parent.parent
    BUILTIN = ROOT / "templates"

    #: Three of Ekahau's own types, recoloured because Ekahau's greys for them
    #: are hard to tell apart on a plan. Removed once by a release that read
    #: "don't change Ekahau's defaults" as covering them; he asked for them
    #: back - "get them back to where they were for my template."
    HIS_COLOURS = {
        "Door, Steel Fire/Exit": "#E85D04",
        "Window, Thick": "#0093EA",
        "Elevator Shaft": "#5FAB4F",
    }

    def _load(self, filename):
        return json.loads((self.BUILTIN / filename).read_text(encoding="utf-8"))

    def test_the_manifest_matches_what_is_on_disk(self):
        """A shipped template missing from the manifest is read as user work."""
        self.assertEqual(set(template_module.SHIPPED_TEMPLATES),
                         template_module.present_builtin_names(),
                         "SHIPPED_TEMPLATES and templates/ disagree - add the "
                         "new file to the manifest, or the migration will "
                         "treat it as somebody's own template and move it")

    def test_both_templates_are_shipped(self):
        for filename in template_module.SHIPPED_TEMPLATES:
            with self.subTest(filename=filename):
                self.assertTrue((self.BUILTIN / filename).is_file())

    def test_the_wd_template_keeps_his_three_colours(self):
        types = {t["name"]: t for t in self._load("WD Template_walltemplate.json")["wallTypes"]}
        for name, colour in self.HIS_COLOURS.items():
            with self.subTest(wall=name):
                self.assertEqual(types[name]["color"].upper(), colour,
                                 f"{name} is back to a colour he did not choose")

    def test_the_wd_template_keeps_his_nine_keyboard_shortcuts(self):
        """Slots 1-9, which is what he draws with. They live in the template."""
        types = self._load("WD Template_walltemplate.json")["wallTypes"]
        bound = {t["keybindNumber"]: t["name"] for t in types if t.get("keybindNumber")}
        self.assertEqual(sorted(bound), list(range(1, 10)),
                         f"the shortcut slots are not 1-9: {sorted(bound)}")

    def test_the_ekahau_template_is_ekahau_unmodified(self):
        """The baseline is only a baseline if nobody has improved it."""
        ekahau = {t["name"]: t for t in self._load("Ekahau Default_walltemplate.json")["wallTypes"]}
        stock = {t["name"]: t for t in
                 json.loads((self.BUILTIN / "ekahau_defaults.json").read_text(encoding="utf-8"))["wallTypes"]}
        self.assertEqual(set(ekahau), set(stock))
        for name, t in stock.items():
            with self.subTest(wall=name):
                self.assertEqual(ekahau[name], t)
        for name, colour in self.HIS_COLOURS.items():
            if name in ekahau:
                with self.subTest(wall=name):
                    self.assertNotEqual(ekahau[name]["color"].upper(), colour,
                                        "the Ekahau baseline has picked up a WD "
                                        "colour, so it is no longer a baseline")

    #: Ekahau's own, confirmed four ways - see the note below. Pinned because
    #: it was briefly mistaken for a value of his that had gone missing.
    ROLLUP_COLOUR = "#646D7E"

    def test_the_roll_up_door_keeps_the_blue_grey_it_has_always_had(self):
        """It is Ekahau's colour, it is correct, and nothing was lost.

        Written down once as "his custom roll-up colour was never saved
        anywhere, he has to supply the hex" - which was wrong, and wrong in a
        repeatable way: the survey saw `#646D7E` on all 57 projects, took
        ubiquity as proof it was the default, and concluded his own value had
        been lost. He said the opposite, and he was right: "this afternoon
        Quick Walls had the roll up door colour correct - basically a blue-grey
        tint instead of just grey." `#646D7E` *is* that blue-grey.

        What settles it:

        * Of 109 projects, **56 have never had his template applied** - their
          steel fire door is still Ekahau's `#999999` rather than his
          `#E85D04` - and every one of those 56 carries `#646D7E` on the
          roll-up. His template cannot have put it there.
        * Five naming variants, 146 instances, no exceptions.
        * v2.100.5 reverted his customisations to Ekahau stock and changed
          exactly three colours, leaving the roll-up alone - it was already
          stock.
        * Every commit since the repository was initialised has this value.

        So both templates carry it and both are right. This test exists so the
        question is not reopened from the wrong end, and so nobody "restores" a
        guessed hex over a correct one.
        """
        for filename in template_module.SHIPPED_TEMPLATES:
            types = {t["name"]: t for t in self._load(filename)["wallTypes"]}
            with self.subTest(template=filename):
                self.assertEqual(types["Door, Steel Rollup"]["color"].upper(),
                                 self.ROLLUP_COLOUR)

    def test_the_wd_template_adds_to_ekahau_rather_than_replacing_it(self):
        wd = {t["name"] for t in self._load("WD Template_walltemplate.json")["wallTypes"]}
        ekahau = {t["name"] for t in self._load("Ekahau Default_walltemplate.json")["wallTypes"]}
        self.assertEqual(ekahau - wd, set(),
                         "the WD set has dropped an Ekahau type")
        self.assertTrue(wd - ekahau, "the WD set adds nothing to Ekahau's")
