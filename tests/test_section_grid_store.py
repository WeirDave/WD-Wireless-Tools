"""Where a project's section grid is remembered, and what the store refuses.

The Report's section grid - columns by rows, the crop on each floor, the
combined cells - used to last one session. It is now kept per project in the
user directory, beside the column grids and for the same reason: the `.esx`
has no member for it, so a round trip through the cloud would drop it, and the
project folder is a synced tree that Cloud Manager scans.

The payload comes from the browser, so every field is re-derived: a size or a
crop that is nonsense decides how many sheets a report prints.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import report_store  # noqa: E402

PROJECT = "11111111-2222-4333-8444-555555555555"
OTHER = "99999999-2222-4333-8444-555555555555"
FLOOR_A = "floor-one"
FLOOR_B = "floor-two"

MERGE = {"cols": 4, "rows": 3, "groups": [{"c0": 0, "r0": 0, "c1": 1, "r1": 0}]}
CROP = {"x": 0.1, "y": 0.2, "w": 0.5, "h": 0.6}


def a_grid(**over):
    grid = {"segCols": 4, "segRows": 3, "cropBoxes": {FLOOR_A: dict(CROP)},
            "segMerges": {FLOOR_A: dict(MERGE)}}
    grid.update(over)
    return grid


class Isolated(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-sections-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._dir = report_store.REPORT_DIR
        self._path = report_store.SECTIONS_PATH
        report_store.REPORT_DIR = self.tmp
        report_store.SECTIONS_PATH = self.tmp / "section_grids.json"
        self.addCleanup(setattr, report_store, "REPORT_DIR", self._dir)
        self.addCleanup(setattr, report_store, "SECTIONS_PATH", self._path)


class SectionGridStorage(Isolated):

    def test_it_lives_in_the_user_directory_and_not_the_install_tree(self):
        """Under SETTINGS_DIR, which both update paths leave alone. Asserted as
        a property rather than by looking for the literal directory name,
        because the suite points WD_USER_DIR at a scratch directory."""
        self.assertEqual(self._path.parent, self._dir)
        self.assertEqual(self._path.name, "section_grids.json")
        self.assertEqual(self._dir.parent, report_store.SETTINGS_DIR)
        self.assertNotIn(ROOT, self._path.parents)

    def test_a_grid_round_trips(self):
        saved = report_store.save_section_grid(PROJECT, a_grid())
        self.assertTrue(saved["ok"], saved.get("error"))
        got = report_store.section_grid_for_project(PROJECT)["project"]
        self.assertEqual((got["cols"], got["rows"]), (4, 3))
        self.assertEqual(got["cropBoxes"], {FLOOR_A: CROP})
        self.assertEqual(got["segMerges"], {FLOOR_A: MERGE})

    def test_projects_are_kept_apart(self):
        report_store.save_section_grid(PROJECT, a_grid())
        report_store.save_section_grid(OTHER, a_grid(segCols=2, segRows=2,
                                                     cropBoxes=None, segMerges=None))
        self.assertEqual(
            report_store.section_grid_for_project(PROJECT)["project"]["cols"], 4)
        other = report_store.section_grid_for_project(OTHER)["project"]
        self.assertEqual(other["cols"], 2)
        self.assertNotIn("cropBoxes", other,
                         "one project's crop was carried to another")

    def test_the_last_size_is_offered_to_a_project_that_has_none(self):
        """What a new project starts from. Only the size - a crop is drawn on
        one project's plans and means nothing on another's."""
        report_store.save_section_grid(PROJECT, a_grid())
        got = report_store.section_grid_for_project(OTHER)
        self.assertIsNone(got["project"])
        self.assertEqual(got["last"], {"cols": 4, "rows": 3})

    def test_last_follows_the_most_recent_save_on_any_project(self):
        report_store.save_section_grid(PROJECT, a_grid())
        report_store.save_section_grid(OTHER, a_grid(segCols=6, segRows=5))
        self.assertEqual(report_store.section_grid_for_project(PROJECT)["last"],
                         {"cols": 6, "rows": 5})

    def test_choosing_auto_is_remembered_and_is_not_the_last_size(self):
        """A project that was set back to Auto must not slide back to the last
        size on the next open, which is what an absent entry means."""
        report_store.save_section_grid(PROJECT, a_grid())
        report_store.save_section_grid(OTHER, a_grid(segCols=None, segRows=None,
                                                     cropBoxes=None, segMerges=None))
        got = report_store.section_grid_for_project(OTHER)["project"]
        self.assertEqual(got, {"auto": True})
        self.assertEqual(report_store.section_grid_for_project(OTHER)["last"],
                         {"cols": 4, "rows": 3}, "choosing Auto erased the last size")

    def test_auto_with_nothing_remembered_stores_nothing(self):
        report_store.save_section_grid(PROJECT, {})
        self.assertEqual(report_store.load_sections()["projects"], {})

    def test_ids_are_stripped_the_same_way_on_both_sides(self):
        report_store.save_section_grid(" " + PROJECT + " ", a_grid())
        self.assertIsNotNone(report_store.section_grid_for_project(PROJECT)["project"])
        self.assertIsNotNone(
            report_store.section_grid_for_project(" " + PROJECT)["project"])

    def test_saving_again_replaces_rather_than_merges(self):
        """A crop taken off must stay off."""
        report_store.save_section_grid(PROJECT, a_grid())
        report_store.save_section_grid(PROJECT, a_grid(cropBoxes=None))
        got = report_store.section_grid_for_project(PROJECT)["project"]
        self.assertNotIn("cropBoxes", got)
        self.assertIn("segMerges", got)

    def test_the_oldest_project_is_what_the_cap_drops(self):
        original = report_store.MAX_SECTION_PROJECTS
        report_store.MAX_SECTION_PROJECTS = 3
        self.addCleanup(setattr, report_store, "MAX_SECTION_PROJECTS", original)
        for n in range(5):
            report_store.save_section_grid("p%d" % n, a_grid())
        self.assertEqual(list(report_store.load_sections()["projects"]),
                         ["p2", "p3", "p4"])


class SectionGridRefusals(Isolated):
    """Nonsense is dropped field by field, so one bad crop does not cost the
    size beside it, and nothing nonsensical reaches a report."""

    def saved(self, **over):
        res = report_store.save_section_grid(PROJECT, a_grid(**over))
        self.assertTrue(res["ok"], res)
        return res["project"] or {}

    def test_a_size_outside_the_dialogs_range_is_dropped(self):
        for cols, rows in ((0, 3), (4, 0), (21, 3), (4, 21), (-1, 2),
                           ("big", 3), (None, 3), (True, 3), (2.5, "x")):
            with self.subTest(cols=cols, rows=rows):
                got = self.saved(segCols=cols, segRows=rows)
                self.assertNotIn("cols", got)

    def test_the_size_needs_both_numbers(self):
        self.assertNotIn("cols", self.saved(segRows=None))

    def test_a_crop_outside_the_plan_is_dropped(self):
        bad = {FLOOR_A: {"x": 0.8, "y": 0, "w": 0.5, "h": 1},       # runs off the right
               FLOOR_B: {"x": 0, "y": 0, "w": 0, "h": 1}}           # nothing left
        self.assertNotIn("cropBoxes", self.saved(cropBoxes=bad))

    def test_a_crop_that_is_not_numbers_is_dropped(self):
        for v in ("left", None, float("nan"), float("inf"), [0]):
            with self.subTest(v=v):
                crop = {FLOOR_A: {"x": v, "y": 0, "w": 0.5, "h": 0.5}}
                self.assertNotIn("cropBoxes", self.saved(cropBoxes=crop))

    def test_one_bad_floor_does_not_cost_the_others(self):
        crops = {FLOOR_A: dict(CROP), FLOOR_B: {"x": "no"}}
        self.assertEqual(self.saved(cropBoxes=crops)["cropBoxes"], {FLOOR_A: CROP})

    def test_a_combined_group_outside_its_grid_is_dropped(self):
        outside = {"cols": 2, "rows": 2, "groups": [{"c0": 0, "r0": 0, "c1": 5, "r1": 0}]}
        self.assertNotIn("segMerges", self.saved(segMerges={FLOOR_A: outside}))

    def test_a_merge_with_no_usable_group_is_dropped(self):
        empty = {"cols": 2, "rows": 2, "groups": []}
        junk = {"cols": 2, "rows": 2, "groups": ["x", {"c0": "a"}]}
        self.assertNotIn("segMerges", self.saved(segMerges={FLOOR_A: empty, FLOOR_B: junk}))

    def test_a_missing_project_is_refused_with_a_sentence(self):
        res = report_store.save_section_grid("", a_grid())
        self.assertFalse(res["ok"])
        self.assertTrue(res["error"])

    def test_a_payload_that_is_not_an_object_is_refused(self):
        self.assertFalse(report_store.save_section_grid(PROJECT, "grid")["ok"])

    def test_a_corrupt_file_reads_as_nothing_remembered(self):
        for junk in ("{not json", "[]", '{"projects": 4}', ""):
            with self.subTest(junk=junk):
                report_store.SECTIONS_PATH.write_text(junk, encoding="utf-8")
                self.assertEqual(report_store.load_sections()["projects"], {})

    def test_an_absurdly_large_file_is_not_read_into_memory(self):
        report_store.SECTIONS_PATH.write_text(
            " " * (report_store.MAX_SECTIONS_BYTES + 10), encoding="utf-8")
        self.assertEqual(report_store.load_sections()["projects"], {})

    def test_the_column_grids_file_is_left_alone(self):
        """Two stores, one directory. Writing one must not disturb the other."""
        report_store.GRIDS_PATH = self.tmp / "grids.json"
        self.addCleanup(setattr, report_store, "GRIDS_PATH",
                        report_store.SETTINGS_DIR / "report" / "grids.json")
        report_store.save_section_grid(PROJECT, a_grid())
        self.assertFalse(report_store.GRIDS_PATH.exists())


class SectionGridRoute(Isolated):
    """The endpoint the Report reaches, through the real Flask app."""

    @classmethod
    def setUpClass(cls):
        from server import app, API_REQUEST_HEADER
        app.config.update(TESTING=True)
        cls.client = app.test_client()
        cls.header = {API_REQUEST_HEADER: "1"}

    def post(self, action, payload):
        return self.client.post(f"/api/report/sections/{action}", json=payload,
                                headers=self.header)

    def test_save_then_get(self):
        r = self.post("save", dict(a_grid(), projectId=PROJECT))
        self.assertTrue(r.get_json()["ok"], r.get_json())
        got = self.post("get", {"projectId": PROJECT}).get_json()
        self.assertEqual((got["project"]["cols"], got["project"]["rows"]), (4, 3))
        self.assertEqual(got["last"], {"cols": 4, "rows": 3})

    def test_a_refusal_is_a_sentence_and_not_a_traceback(self):
        body = self.post("save", {"segCols": 4}).get_json()
        self.assertFalse(body["ok"])
        self.assertNotIn("Traceback", body["error"])

    def test_an_unknown_action_is_rejected(self):
        self.assertEqual(self.post("wipe", {"projectId": PROJECT}).status_code, 404)

    def test_an_empty_body_does_not_raise(self):
        for action in ("get", "save"):
            with self.subTest(action=action):
                r = self.client.post(f"/api/report/sections/{action}",
                                     headers=self.header)
                self.assertIn(r.status_code, (200, 400))
                self.assertNotIn("Traceback", r.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
