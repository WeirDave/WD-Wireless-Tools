"""Export, wreck the settings, import, and check every value came back.

This exists because a night of testing overwrote his live settings: Quick Walls
defaults gone, wall-type colours gone, and the keyboard shortcuts survived only
because he had typed them into OneNote. So the test that matters is not "does
export produce a file" but "does a restore put back exactly what was there".

The keyboard-shortcut case is called out separately because it is the one that
would be quietly missed: `keybindNumber` is a field on each wall type inside a
wall template, not a store of its own, so a backup that skipped `templates/`
would look complete and lose them.
"""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tools import settings, settings_backup


class Harness(unittest.TestCase):
    """A throwaway user-data directory, so nothing here can touch his."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.settings_file = self.root / "settings.json"
        self.p1 = patch.object(settings, "SETTINGS_FILE", self.settings_file)
        self.p1.start()
        self.addCleanup(self.p1.stop)
        self.addCleanup(self.tmp.cleanup)

    def write_settings(self, **overrides):
        s = copy.deepcopy(settings.DEFAULTS)
        for dotted, value in overrides.items():
            node = s
            parts = dotted.split(".")
            for key in parts[:-1]:
                node = node.setdefault(key, {})
            node[parts[-1]] = value
        settings.save_settings(s, _path=self.settings_file)
        return s

    def write_template(self, name="My Walls_walltemplate.json", binds=(1, 2, 3)):
        d = self.root / "templates"
        d.mkdir(parents=True, exist_ok=True)
        wall_types = [
            {"name": "Drywall", "color": "#88CCEE", "attenuation": 3.0,
             "keybindNumber": binds[0] if len(binds) > 0 else None},
            {"name": "Brick", "color": "#DD7744", "attenuation": 10.0,
             "keybindNumber": binds[1] if len(binds) > 1 else None},
            {"name": "Glass", "color": "#44AA99", "attenuation": 6.0,
             "keybindNumber": binds[2] if len(binds) > 2 else None},
        ]
        for w in wall_types:
            if w["keybindNumber"] is None:
                del w["keybindNumber"]
        (d / name).write_text(json.dumps({"wallTypes": wall_types}, indent=2),
                              encoding="utf-8")
        return wall_types


class TheRoundTripReturnsEveryValue(Harness):

    def test_export_then_wreck_then_import(self):
        original = self.write_settings(**{
            "global.output_dir": str(self.root / "Projects"),
            "global.create_folder_template": "{site_code}",
            "walls.units": "imperial",
            "walls.default_template": "My Walls",
            "walls.auto_apply_template": True,
            "walls.reveal_source_after_save": False,
            "cloud.merge_rule": "skip",
            "cloud.live_interval_ms": 60000,
            "organizer.create_folder_template": "{site_code} - {site_name}",
        })
        walls = self.write_template()

        bundle = settings_backup.export_bundle(root=self.root)

        # Now do what the sweep did: overwrite everything and delete the
        # template, shortcuts and all.
        self.write_settings(**{
            "global.create_folder_template": "",
            "walls.units": "metric",
            "walls.default_template": "",
            "walls.auto_apply_template": False,
            "walls.reveal_source_after_save": True,
            "cloud.merge_rule": "ask",
            "cloud.live_interval_ms": 15000,
            "organizer.create_folder_template": "",
        })
        (self.root / "templates" / "My Walls_walltemplate.json").unlink()

        settings_backup.apply_import(bundle, sections=("settings", "files"),
                                     root=self.root)

        restored = settings.load_settings(_path=self.settings_file)
        for dotted in ("global.create_folder_template", "walls.units",
                       "walls.default_template", "walls.auto_apply_template",
                       "walls.reveal_source_after_save", "cloud.merge_rule",
                       "cloud.live_interval_ms",
                       "organizer.create_folder_template"):
            with self.subTest(setting=dotted):
                node_o, node_r = original, restored
                for key in dotted.split("."):
                    node_o, node_r = node_o[key], node_r[key]
                self.assertEqual(node_r, node_o)

        back = json.loads((self.root / "templates" /
                           "My Walls_walltemplate.json").read_text(encoding="utf-8"))
        self.assertEqual(back["wallTypes"], walls)

    def test_the_keyboard_shortcuts_come_back(self):
        """The one he lost. They are not a store of their own - they ride on
        the wall types inside the template - so a backup that skipped
        templates/ would look complete and lose them silently."""
        self.write_settings()
        self.write_template(binds=(4, 7, 9))
        bundle = settings_backup.export_bundle(root=self.root)

        (self.root / "templates" / "My Walls_walltemplate.json").unlink()
        settings_backup.apply_import(bundle, root=self.root)

        back = json.loads((self.root / "templates" /
                           "My Walls_walltemplate.json").read_text(encoding="utf-8"))
        binds = {w["name"]: w.get("keybindNumber") for w in back["wallTypes"]}
        self.assertEqual(binds, {"Drywall": 4, "Brick": 7, "Glass": 9})

    def test_the_wall_colours_come_back(self):
        self.write_settings()
        self.write_template()
        bundle = settings_backup.export_bundle(root=self.root)
        (self.root / "templates" / "My Walls_walltemplate.json").write_text(
            json.dumps({"wallTypes": [{"name": "Drywall", "color": "#000000"}]}),
            encoding="utf-8")
        settings_backup.apply_import(bundle, root=self.root)
        back = json.loads((self.root / "templates" /
                           "My Walls_walltemplate.json").read_text(encoding="utf-8"))
        colours = {w["name"]: w["color"] for w in back["wallTypes"]}
        self.assertEqual(colours, {"Drywall": "#88CCEE", "Brick": "#DD7744",
                                   "Glass": "#44AA99"})


class NothingSecretLeavesTheMachine(Harness):

    def test_the_saved_login_is_never_exported(self):
        self.write_settings()
        (self.root / "cookies.enc").write_bytes(b"not a real session")
        bundle = settings_backup.export_bundle(root=self.root)
        blob = json.dumps(bundle)
        self.assertNotIn("cookies.enc", bundle["files"])
        self.assertNotIn("not a real session", blob)

    def test_per_project_machine_state_is_not_dragged_along(self):
        """acorn_state is ~1800 files of where he got to, not how he works."""
        self.write_settings()
        d = self.root / "acorn_state"
        d.mkdir()
        (d / "deadbeef.json").write_text("{}", encoding="utf-8")
        bundle = settings_backup.export_bundle(root=self.root)
        self.assertFalse([k for k in bundle["files"] if "acorn_state" in k])

    def test_a_migration_marker_does_not_travel(self):
        """`templates/.migrated` records that a one-time move already ran here.
        Carried to a machine where it has not, it would skip the migration and
        the legacy templates it was supposed to rescue would stay lost."""
        self.write_settings()
        d = self.root / "templates"
        d.mkdir(parents=True, exist_ok=True)
        (d / ".migrated").write_text("", encoding="utf-8")
        self.write_template()
        bundle = settings_backup.export_bundle(root=self.root)
        self.assertNotIn("templates/.migrated", bundle["files"])
        self.assertIn("templates/My Walls_walltemplate.json", bundle["files"])

    def test_an_import_cannot_write_outside_the_user_directory(self):
        self.write_settings()
        evil = {"schema": 1, "settings": {},
                "files": {"../../escaped.json": {"json": {"x": 1}},
                          "cookies.enc": {"base64": "AAAA"}}}
        result = settings_backup.apply_import(evil, root=self.root)
        self.assertIn("refused", result["applied"])
        self.assertEqual(sorted(result["applied"]["refused"]),
                         ["../../escaped.json", "cookies.enc"])
        self.assertFalse((self.root.parent.parent / "escaped.json").exists())


class ThePreviewSaysWhatWillChange(Harness):
    """He has had settings change underneath him twice in one night and should
    never again be surprised by a write."""

    def test_it_separates_added_changed_and_identical(self):
        self.write_settings(**{"walls.units": "imperial",
                               "cloud.live_interval_ms": 60000})
        bundle = settings_backup.export_bundle(root=self.root)
        self.write_settings(**{"walls.units": "metric",
                               "cloud.live_interval_ms": 60000})

        p = settings_backup.preview_import(bundle, root=self.root)
        self.assertTrue(p["ok"])
        changed = {c["key"]: (c["old"], c["new"]) for c in p["settings"]["change"]}
        self.assertEqual(changed.get("walls.units"), ("metric", "imperial"))
        same = {c["key"] for c in p["settings"]["same"]}
        self.assertIn("cloud.live_interval_ms", same)
        self.assertTrue(p["willChangeAnything"])

    def test_an_identical_import_says_it_would_change_nothing(self):
        self.write_settings()
        bundle = settings_backup.export_bundle(root=self.root)
        p = settings_backup.preview_import(bundle, root=self.root)
        self.assertFalse(p["willChangeAnything"])

    def test_it_writes_nothing(self):
        self.write_settings(**{"walls.units": "imperial"})
        bundle = settings_backup.export_bundle(root=self.root)
        self.write_settings(**{"walls.units": "metric"})
        settings_backup.preview_import(bundle, root=self.root)
        now = settings.load_settings(_path=self.settings_file)
        self.assertEqual(now["walls"]["units"], "metric")

    def test_a_path_from_another_machine_is_flagged_and_checked(self):
        """A folder from the home machine is wrong on the work one, so the
        preview says whether it exists here rather than assuming."""
        self.write_settings(**{"global.output_dir": r"D:\NoSuchPlace\Projects"})
        bundle = settings_backup.export_bundle(root=self.root)
        p = settings_backup.preview_import(bundle, root=self.root)
        flagged = {f["key"]: f for f in p["machineSpecific"]}
        self.assertIn("global.output_dir", flagged)
        self.assertFalse(flagged["global.output_dir"]["existsHere"])

    def test_a_path_that_does_exist_here_is_not_alarming(self):
        real = self.root / "Projects"
        real.mkdir()
        self.write_settings(**{"global.output_dir": str(real)})
        bundle = settings_backup.export_bundle(root=self.root)
        p = settings_backup.preview_import(bundle, root=self.root)
        flagged = {f["key"]: f for f in p["machineSpecific"]}
        self.assertTrue(flagged["global.output_dir"]["existsHere"])


class AnUnknownSchemaIsReportedNotDropped(Harness):

    def test_a_newer_export_is_read_as_far_as_it_can_be(self):
        self.write_settings()
        bundle = settings_backup.export_bundle(root=self.root)
        bundle["schema"] = settings_backup.SCHEMA_VERSION + 5
        bundle["settings"]["somethingNew"] = {"added_later": True}

        p = settings_backup.preview_import(bundle, root=self.root)
        self.assertTrue(p["ok"])
        self.assertTrue(p["schemaNewer"])
        self.assertTrue(p["schemaNotes"])
        unknown = {u["key"] for u in p["settings"]["unknown"]}
        self.assertIn("somethingNew.added_later", unknown,
                      "an unrecognised key must be named, never silently dropped")

    def test_a_file_with_no_schema_is_refused_with_a_reason(self):
        p = settings_backup.preview_import({"hello": "world"}, root=self.root)
        self.assertFalse(p["ok"])
        self.assertIn("schema version", p["error"])

    def test_something_that_is_not_a_bundle_at_all(self):
        p = settings_backup.preview_import("not even a dict", root=self.root)
        self.assertFalse(p["ok"])


class ItBacksUpBeforeItWrites(Harness):

    def test_an_import_leaves_a_copy_of_what_was_there(self):
        self.write_settings(**{"walls.units": "imperial"})
        bundle = settings_backup.export_bundle(root=self.root)
        self.write_settings(**{"walls.units": "metric"})

        result = settings_backup.apply_import(bundle, root=self.root)
        self.assertTrue(result["backup"])
        saved = json.loads(Path(result["backup"]).read_text(encoding="utf-8"))
        self.assertEqual(saved["walls"]["units"], "metric",
                         "the backup holds what was there before the import")

    def test_the_copy_is_named_so_its_own_pruning_can_find_it(self):
        """`_prune_copies` matches `<stem>.backup-<stamp><ext>` beside the
        file. Get the name wrong - the stamp after the extension, say - and
        nothing ever matches it again, so every copy is kept for ever. This
        module is the last thing in the suite that copies a file aside, so
        there is no shared retention left to lean on."""
        self.write_settings()
        result = settings_backup.backup_current(root=self.root)
        dest = Path(result["backup"])
        self.assertTrue(dest.exists())
        self.assertEqual(".json", dest.suffix)
        self.assertRegex(dest.stem, r"^settings\.backup-\d{8}-\d{6}$")
        self.assertEqual(self.root, dest.parent)

    def test_asking_for_none_still_leaves_one_step_back(self):
        """keep=0 is about routine copies piling up. An import is a deliberate
        destructive act and its undo is part of the act, so this one is floored
        at one however low the caller goes."""
        self.write_settings()
        result = settings_backup.backup_current(root=self.root, keep=0)
        self.assertEqual(result["keep"], 1)
        self.assertTrue(Path(result["backup"]).exists())

    def test_a_number_the_caller_gives_is_otherwise_respected(self):
        self.write_settings()
        result = settings_backup.backup_current(root=self.root, keep=2)
        self.assertEqual(result["keep"], 2)

    def test_the_default_is_the_modules_own_constant(self):
        self.write_settings()
        result = settings_backup.backup_current(root=self.root)
        self.assertEqual(settings_backup.KEEP_COPIES, result["keep"])


class TheBundleIsReadable(Harness):

    def test_it_carries_a_schema_and_a_timestamp(self):
        self.write_settings()
        b = settings_backup.export_bundle(root=self.root)
        self.assertEqual(b["schema"], settings_backup.SCHEMA_VERSION)
        self.assertTrue(b["exportedAt"])
        self.assertEqual(b["app"], settings_backup.APP_NAME)

    def test_his_own_values_are_legible_in_it(self):
        """He should be able to open the file and see his settings, not a
        base64 blob."""
        self.write_settings(**{"walls.units": "imperial"})
        self.write_template()
        b = settings_backup.export_bundle(root=self.root)
        self.assertEqual(b["settings"]["walls"]["units"], "imperial")
        tpl = b["files"]["templates/My Walls_walltemplate.json"]
        self.assertIn("json", tpl)
        self.assertEqual(tpl["json"]["wallTypes"][0]["name"], "Drywall")

    def test_the_filename_says_what_it_is_and_when(self):
        name = settings_backup.suggested_filename()
        self.assertTrue(name.startswith("wd-wireless-tools-settings-"))
        self.assertTrue(name.endswith(".json"))

    def test_it_says_what_it_deliberately_left_out(self):
        self.write_settings()
        b = settings_backup.export_bundle(root=self.root)
        self.assertIn("cookies.enc", b["notes"]["excluded"])
        self.assertIn("keybindNumber", b["notes"]["keyboardShortcuts"])


class UiStateIsExportedButNeverRestored(Harness):
    """The registry's own rule, applied.

    ui-state "deliberately stays in localStorage: syncing a collapsed panel
    between machines would be a regression, not a feature". So the panel widths
    are in the file - a backup that quietly omits things is not a backup, and
    he should be able to open it and see everything - and a restore leaves them
    alone.
    """

    BROWSER = {
        "wd-theme": "light",
        "wd-sharing-group": "some-group",
        "wd.walls.swapSidebarWidth": "420",
        "wd-heldback-open": "1",
        "wd-match-help-seen": "1",
    }

    def test_everything_is_in_the_file(self):
        self.write_settings()
        b = settings_backup.export_bundle(browser=self.BROWSER, root=self.root)
        self.assertEqual(b["browser"], self.BROWSER)

    def test_only_the_ones_that_follow_the_person_come_back(self):
        self.write_settings()
        b = settings_backup.export_bundle(browser=self.BROWSER, root=self.root)
        r = settings_backup.apply_import(
            b, sections=("settings", "files", "browser"), root=self.root)
        self.assertEqual(sorted(r["browser"]), ["wd-sharing-group", "wd-theme"])

    def test_the_panel_widths_are_named_as_skipped_rather_than_dropped(self):
        """Silently not restoring something is how a restore comes to be
        mistrusted. The caller is told what it left alone."""
        self.write_settings()
        b = settings_backup.export_bundle(browser=self.BROWSER, root=self.root)
        r = settings_backup.apply_import(
            b, sections=("settings", "files", "browser"), root=self.root)
        self.assertIn("wd.walls.swapSidebarWidth", r["browserSkipped"])
        self.assertIn("wd-heldback-open", r["browserSkipped"])

    def test_the_preview_only_promises_what_it_will_do(self):
        """Listing a panel width as "will change" and then not changing it
        teaches him to stop reading previews."""
        self.write_settings()
        b = settings_backup.export_bundle(browser=self.BROWSER, root=self.root)
        p = settings_backup.preview_import(b, browser={}, root=self.root)
        promised = {e["key"] for e in p["browser"]["add"] + p["browser"]["change"]}
        self.assertEqual(promised, {"wd-theme", "wd-sharing-group"})
        self.assertIn("wd.walls.swapSidebarWidth", p["browserNotRestored"])

    def test_the_restorable_list_is_declared_in_the_registry(self):
        """Both exceptions are filed as ui-state today. A known mismatch,
        recorded here so nobody 'fixes' it by deleting the exception."""
        reg = json.loads((Path(__file__).resolve().parent.parent / "web" /
                          "assets" / "settings-registry.json")
                         .read_text(encoding="utf-8"))
        declared = {k["key"] for k in reg["browser_only"]["keys"]}
        for key in settings_backup.RESTORABLE_BROWSER_KEYS:
            with self.subTest(key=key):
                self.assertIn(key, declared)


class AnAutomaticDumpBeforeSomethingRisky(Harness):

    def test_it_writes_a_full_bundle_into_its_own_folder(self):
        self.write_settings(**{"walls.units": "imperial"})
        self.write_template()
        r = settings_backup.auto_dump("update", root=self.root)
        self.assertTrue(r["ok"])
        path = Path(r["written"])
        self.assertEqual(path.parent.name, settings_backup.AUTO_DIR_NAME)
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["settings"]["walls"]["units"], "imperial")
        self.assertIn("templates/My Walls_walltemplate.json", saved["files"])
        self.assertEqual(saved["takenBecause"], "update")

    def test_zero_really_switches_it_off(self):
        """These are the accumulating kind, so unlike `backup_current` this one
        honours a zero rather than flooring it at one."""
        self.write_settings()
        r = settings_backup.auto_dump("update", root=self.root, keep=0)
        self.assertIsNone(r["written"])
        self.assertFalse((self.root / settings_backup.AUTO_DIR_NAME).exists())

    def test_retention_applies_and_the_names_can_be_pruned(self):
        import time
        self.write_settings()
        for _ in range(4):
            settings_backup.auto_dump("update", root=self.root, keep=2)
            time.sleep(1.05)
        kept = sorted((self.root / settings_backup.AUTO_DIR_NAME).glob("*.json"))
        self.assertEqual(len(kept), 2)
        for f in kept:
            with self.subTest(file=f.name):
                self.assertRegex(
                    f.stem, r"^settings-update\.backup-\d{8}-\d{6}$",
                    "a name this shape is what _prune_copies matches on")

    def test_one_reason_does_not_evict_another(self):
        """A run of updates must not push out the dump taken before the last
        import: five copies of one must not hide the only copy of another."""
        self.write_settings()
        settings_backup.auto_dump("import", root=self.root, keep=1)
        settings_backup.auto_dump("update", root=self.root, keep=1)
        names = sorted(p.name for p in
                       (self.root / settings_backup.AUTO_DIR_NAME).glob("*.json"))
        self.assertTrue(any("import" in n for n in names), names)
        self.assertTrue(any("update" in n for n in names), names)

    def test_it_never_fails_the_operation_it_protects(self):
        """An update that refuses to run because its safety net broke is worse
        than one with no safety net."""
        with patch.object(settings_backup, "export_bundle",
                          side_effect=OSError("disk full")):
            r = settings_backup.auto_dump("update", root=self.root)
        self.assertFalse(r["ok"])
        self.assertIsNone(r["written"])

    def test_the_updater_takes_one_before_it_runs(self):
        src = (Path(__file__).resolve().parent.parent / "tools" /
               "updater.py").read_text(encoding="utf-8")
        block = src[src.index("def perform_update("):]
        block = block[:block.index("chosen = mode")]
        self.assertIn('_dump_settings_first("update"', block)


class TheLastExportIsDated(Harness):

    def test_taking_an_export_records_when(self):
        self.write_settings()
        when = settings_backup.note_export_taken()
        self.assertTrue(when)
        got = settings.load_settings(_path=self.settings_file)
        self.assertEqual(got["global"]["last_settings_export"], when)

    def test_it_is_declared_as_internal_state_not_a_setting(self):
        """No control and not a choice, so it belongs in the registry's
        internal list rather than as an entry with a home."""
        reg = json.loads((Path(__file__).resolve().parent.parent / "web" /
                          "assets" / "settings-registry.json")
                         .read_text(encoding="utf-8"))
        self.assertIn("global.last_settings_export", reg["internal"]["keys"])

    def test_an_automatic_dump_does_not_count_as_one_he_took(self):
        """Otherwise the page says his backup is fresh because the suite
        protected itself, which is reassurance he has not earned."""
        self.write_settings()
        settings_backup.auto_dump("update", root=self.root)
        got = settings.load_settings(_path=self.settings_file)
        self.assertEqual(got["global"]["last_settings_export"], "")


if __name__ == "__main__":
    unittest.main()
