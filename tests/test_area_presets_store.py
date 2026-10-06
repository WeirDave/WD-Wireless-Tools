"""The attenuation-area presets he keeps survive, stay out of wall templates, and
cannot be damaged by a bad entry.

Quick Walls' Attenuation Areas tab keeps two presets that ship with the app and
any number he keeps from a project. The kept ones are his own work, so they live
in the user directory (an update must not touch them), are carried by the
settings export, and are checked on the way in and again on the way out - a file
that was hand-edited or half written costs the bad entry, not the tab.

Every name here is invented.
"""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from server import API_REQUEST_HEADER, app
from tools import area_presets, settings_backup

ROOT = Path(__file__).resolve().parent.parent


def preset(name="Invented Reeds", **over):
    p = {"name": name, "color": "#405060", "lowerEdgeFt": 0, "upperEdgeFt": 6,
         "attenuationDbPerFt": {"TWO": 0.5, "FIVE": 0.75, "SIX": 1.25}}
    p.update(over)
    return p


class InAScratchDirectory(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        d = Path(self._tmp.name)
        for target, value in (("USER_DIR", d), ("STORE", d / "attenuation-area-presets.json")):
            p = mock.patch.object(area_presets, target, value)
            p.start()
            self.addCleanup(p.stop)
        self.dir = d


class WhatIsStoredTests(InAScratchDirectory):
    def test_a_kept_preset_is_listed_after_the_built_in_ones_and_survives_a_reload(self):
        area_presets.save(preset())
        names = [p["name"] for p in area_presets.all_presets()]
        self.assertEqual(names[-1], "Invented Reeds")
        self.assertEqual(names[:2], ["Tree Canopy", "Shrubbery/Low Plants"])
        kept = [p for p in area_presets.all_presets() if p["name"] == "Invented Reeds"][0]
        self.assertFalse(kept["builtin"])
        self.assertTrue(all(p["builtin"] for p in area_presets.shipped()))
        self.assertEqual(kept["attenuationDbPerFt"], {"TWO": 0.5, "FIVE": 0.75, "SIX": 1.25})

    def test_keeping_the_same_name_again_replaces_it_and_does_not_duplicate(self):
        area_presets.save(preset())
        area_presets.save(preset(" invented  REEDS ", upperEdgeFt=9))
        mine = area_presets.kept()
        self.assertEqual(len(mine), 1)
        self.assertEqual(mine[0]["upperEdgeFt"], 9)

    def test_an_empty_upper_edge_is_kept_as_none_and_means_the_ceiling(self):
        area_presets.save(preset(upperEdgeFt=None))
        self.assertIsNone(area_presets.kept()[0]["upperEdgeFt"])

    def test_a_built_in_preset_cannot_be_replaced_or_removed(self):
        with self.assertRaises(ValueError) as c:
            area_presets.save(preset("tree canopy"))
        self.assertIn("built-in", str(c.exception))
        with self.assertRaises(ValueError):
            area_presets.delete("Tree Canopy")
        self.assertEqual(area_presets.kept(), [])

    def test_removing_one_leaves_the_others_and_a_missing_one_says_so(self):
        area_presets.save(preset("Invented A"))
        area_presets.save(preset("Invented B"))
        area_presets.delete("invented a")
        self.assertEqual([p["name"] for p in area_presets.kept()], ["Invented B"])
        with self.assertRaises(ValueError):
            area_presets.delete("Invented A")

    def test_nothing_is_written_for_a_refused_preset(self):
        for bad in (preset(name="  "), preset(color="red"), preset(lowerEdgeFt=-1),
                    preset(lowerEdgeFt=5, upperEdgeFt=5), preset(upperEdgeFt=float("inf")),
                    preset(attenuationDbPerFt={"TWO": 1, "FIVE": 1}),
                    preset(attenuationDbPerFt={"TWO": 1, "FIVE": True, "SIX": 1}),
                    preset(name="x" * 81), "not an object"):
            with self.subTest(bad=str(bad)[:40]):
                with self.assertRaises(ValueError):
                    area_presets.save(bad)
        self.assertFalse((self.dir / "attenuation-area-presets.json").exists())

    def test_a_damaged_file_costs_the_bad_entry_not_the_tab(self):
        (self.dir / "attenuation-area-presets.json").write_text(json.dumps({"presets": [
            preset("Invented Good"), {"name": "Invented Bad", "color": "nope"}, 7, None,
            preset("tree canopy")]}), encoding="utf-8")
        names = [p["name"] for p in area_presets.all_presets()]
        self.assertIn("Invented Good", names)
        self.assertNotIn("Invented Bad", names)
        self.assertEqual(names.count("Tree Canopy"), 1, "a kept copy must not shadow the built-in")
        (self.dir / "attenuation-area-presets.json").write_text("{ not json", encoding="utf-8")
        self.assertEqual([p["name"] for p in area_presets.all_presets()],
                         ["Tree Canopy", "Shrubbery/Low Plants"])

    def test_a_write_goes_through_a_rename_and_leaves_no_temp_file(self):
        area_presets.save(preset())
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()),
                         ["attenuation-area-presets.json"])

    def test_the_cap_is_enforced(self):
        with mock.patch.object(area_presets, "MAX_PRESETS", 2):
            area_presets.save(preset("Invented A"))
            area_presets.save(preset("Invented B"))
            with self.assertRaises(ValueError):
                area_presets.save(preset("Invented C"))
            area_presets.save(preset("Invented A", upperEdgeFt=7))   # replacing is not growing


class KeptApartFromWallTemplatesTests(unittest.TestCase):
    def test_the_presets_file_is_not_a_wall_template_and_templates_carry_no_areas(self):
        self.assertNotIn("_walltemplate", area_presets.STORE.name)
        self.assertNotIn("_walltemplate", area_presets.SHIPPED.name)
        for tpl in (ROOT / "templates").glob("*_walltemplate.json"):
            with self.subTest(template=tpl.name):
                doc = json.loads(tpl.read_text(encoding="utf-8"))
                self.assertFalse([k for k in doc if "ttenuation" in k], tpl.name)


class TheExportCarriesThemTests(unittest.TestCase):
    def test_the_settings_export_lists_the_presets_file(self):
        self.assertIn("attenuation-area-presets.json", settings_backup.EXPORT_FILES)


class EndpointTests(InAScratchDirectory):
    def post(self, action, payload=None):
        c = app.test_client()
        r = c.post("/api/walls/" + action, json=payload or {}, headers={API_REQUEST_HEADER: "1"})
        try:
            return r.status_code, r.get_json()
        finally:
            r.close()

    def test_list_save_and_delete_round_trip_over_http(self):
        code, body = self.post("area_presets")
        self.assertEqual((code, body["ok"]), (200, True))
        self.assertEqual(len(body["presets"]), 2)
        code, body = self.post("area_preset_save", {"preset": preset()})
        self.assertTrue(body["ok"])
        self.assertEqual(body["presets"][-1]["name"], "Invented Reeds")
        code, body = self.post("area_preset_delete", {"name": "Invented Reeds"})
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["presets"]), 2)

    def test_a_refusal_is_a_400_carrying_only_the_reason(self):
        code, body = self.post("area_preset_save", {"preset": preset(color="red")})
        self.assertEqual(code, 400)
        self.assertEqual(set(body), {"ok", "error"})
        self.assertFalse(body["ok"])
        self.assertIn("#RRGGBB", body["error"])
        self.assertNotIn("Traceback", json.dumps(body))
        code, body = self.post("area_preset_delete", {"name": "Tree Canopy"})
        self.assertEqual(code, 400)
        self.assertIn("built-in", body["error"])

    def test_a_request_without_the_app_header_is_refused_like_every_api_call(self):
        c = app.test_client()
        r = c.post("/api/walls/area_presets", json={})
        try:
            self.assertNotEqual(r.status_code, 200)
        finally:
            r.close()


if __name__ == "__main__":
    unittest.main()
