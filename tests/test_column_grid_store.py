"""Where a floor's grid calibration lives, and what it refuses to store.

It is deliberately **not** in the `.esx`. Ekahau has no member for it, so a
round trip through the cloud - or through Ekahau AI Pro - would drop it
silently and the Grid column would stop appearing with nothing to say why. It
sits beside the cover image in `~/.wd_wireless_tools/report/`, which both
update paths are required to leave alone.

Every field is re-derived on the way in rather than trusted, because the
payload comes from the browser and a calibration that is nonsense prints a
wrong bay number on a drawing somebody climbs a ladder from.
"""
from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import report_store  # noqa: E402

PROJECT = "11111111-2222-4333-8444-555555555555"
FLOOR_A = "floor-one"
FLOOR_B = "floor-two"


def a_point(x=100.0, y=100.0, col=0, row=1):
    return {"x": x, "y": y, "col": col, "row": row}


def a_grid(**over):
    grid = {"a": a_point(), "b": a_point(700.0, 580.0, 6, 7), "lettersAxis": "x"}
    grid.update(over)
    return grid


class GridStorage(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-grid-store-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self._orig_dir = report_store.REPORT_DIR
        self._orig_path = report_store.GRIDS_PATH
        report_store.REPORT_DIR = self.tmp
        report_store.GRIDS_PATH = self.tmp / "grids.json"
        self.addCleanup(setattr, report_store, "REPORT_DIR", self._orig_dir)
        self.addCleanup(setattr, report_store, "GRIDS_PATH", self._orig_path)

    def test_it_lives_beside_the_cover_image_in_the_user_directory(self):
        """Not in the install tree, which an update replaces, and not in the
        .esx, which has nowhere to put it.

        Asserted as "under SETTINGS_DIR" rather than by looking for
        ".wd_wireless_tools" in the path: the suite sets WD_USER_DIR to a
        scratch directory, so the literal name is absent during a test run
        while the property - user data, outside the install - holds exactly as
        it does on a real machine. Matching the string would have passed only
        by accident of where the tests happened to run.
        """
        self.assertEqual(self._orig_path.parent, self._orig_dir)
        self.assertEqual(self._orig_path.name, "grids.json")
        self.assertEqual(self._orig_dir.parent, report_store.SETTINGS_DIR)
        self.assertNotIn(ROOT, self._orig_path.parents,
                         "the calibration is inside the install tree, which an "
                         "update replaces")

    def test_a_calibration_round_trips(self):
        saved = report_store.save_grid(PROJECT, FLOOR_A, a_grid())
        self.assertTrue(saved["ok"], saved.get("error"))
        got = report_store.grids_for_project(PROJECT)["floors"][FLOOR_A]
        self.assertEqual(got["a"], a_point())
        self.assertEqual(got["b"], a_point(700.0, 580.0, 6, 7))
        self.assertEqual(got["lettersAxis"], "x")

    def test_floors_are_kept_apart(self):
        """One building, two floors, two different grids - which is ordinary,
        because a mezzanine rarely shares the slab's column lines."""
        report_store.save_grid(PROJECT, FLOOR_A, a_grid())
        report_store.save_grid(PROJECT, FLOOR_B,
                               a_grid(a=a_point(50.0, 50.0, 2, 4)))
        floors = report_store.grids_for_project(PROJECT)["floors"]
        self.assertEqual(sorted(floors), [FLOOR_A, FLOOR_B])
        self.assertEqual(floors[FLOOR_B]["a"]["col"], 2)
        self.assertEqual(floors[FLOOR_A]["a"]["col"], 0)

    def test_clearing_one_floor_leaves_the_other(self):
        """Turning the reference off for a floor this cannot model is the
        documented answer, so it has to be reachable without losing the floors
        that do work."""
        report_store.save_grid(PROJECT, FLOOR_A, a_grid())
        report_store.save_grid(PROJECT, FLOOR_B, a_grid())
        report_store.clear_grid(PROJECT, FLOOR_A)
        floors = report_store.grids_for_project(PROJECT)["floors"]
        self.assertEqual(sorted(floors), [FLOOR_B])

    def test_clearing_the_last_floor_removes_the_project_entirely(self):
        report_store.save_grid(PROJECT, FLOOR_A, a_grid())
        report_store.clear_grid(PROJECT, FLOOR_A)
        self.assertEqual(report_store.grids_for_project(PROJECT)["floors"], {})
        self.assertEqual(report_store.load_grids()["projects"], {})

    def test_clearing_a_floor_that_was_never_set_is_not_an_error(self):
        self.assertTrue(report_store.clear_grid(PROJECT, "nope")["ok"])

    def test_an_unknown_project_reads_as_uncalibrated(self):
        self.assertEqual(report_store.grids_for_project("nobody")["floors"], {})


class GridStorageRefusals(unittest.TestCase):
    """A calibration that is nonsense is refused rather than stored.

    Stored, it would print a confidently wrong bay number, which is the exact
    failure this feature exists to avoid - the installer has no way to tell.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-grid-refuse-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        report_store.REPORT_DIR = self.tmp
        report_store.GRIDS_PATH = self.tmp / "grids.json"
        self.addCleanup(setattr, report_store, "REPORT_DIR",
                        report_store.SETTINGS_DIR / "report")
        self.addCleanup(setattr, report_store, "GRIDS_PATH",
                        report_store.SETTINGS_DIR / "report" / "grids.json")

    def assertRefused(self, result, phrase=""):
        self.assertFalse(result["ok"], f"accepted: {result}")
        self.assertTrue(result.get("error"), "refused with no reason")
        if phrase:
            self.assertIn(phrase.lower(), result["error"].lower())

    def test_two_points_on_one_line_are_refused(self):
        self.assertRefused(
            report_store.save_grid(PROJECT, FLOOR_A,
                                   a_grid(b=a_point(700.0, 580.0, 0, 7))),
            "both directions")
        self.assertRefused(
            report_store.save_grid(PROJECT, FLOOR_A,
                                   a_grid(b=a_point(700.0, 580.0, 6, 1))),
            "both directions")

    def test_a_point_missing_a_field_is_refused(self):
        for missing in ("x", "y", "col", "row"):
            with self.subTest(missing=missing):
                bad = a_point()
                del bad[missing]
                self.assertRefused(
                    report_store.save_grid(PROJECT, FLOOR_A, a_grid(a=bad)))

    def test_a_label_below_the_first_line_is_refused(self):
        """There is no column before A and no line before 1."""
        self.assertRefused(
            report_store.save_grid(PROJECT, FLOOR_A, a_grid(a=a_point(col=-1))))
        self.assertRefused(
            report_store.save_grid(PROJECT, FLOOR_A, a_grid(a=a_point(row=0))))

    def test_coordinates_that_are_not_numbers_are_refused(self):
        for value in ("over there", None, float("inf"), float("nan"), [1]):
            with self.subTest(value=value):
                self.assertRefused(
                    report_store.save_grid(PROJECT, FLOOR_A,
                                           a_grid(a=a_point(x=value))))

    def test_a_missing_floor_or_project_is_refused(self):
        self.assertRefused(report_store.save_grid("", FLOOR_A, a_grid()))
        self.assertRefused(report_store.save_grid(PROJECT, "", a_grid()))

    def test_an_unknown_letters_axis_falls_back_rather_than_storing_junk(self):
        """Only two axes exist. Anything else is x, which is what the picker
        opens on."""
        report_store.save_grid(PROJECT, FLOOR_A, a_grid(lettersAxis="sideways"))
        got = report_store.grids_for_project(PROJECT)["floors"][FLOOR_A]
        self.assertEqual(got["lettersAxis"], "x")

    def test_a_corrupt_file_reads_as_nothing_calibrated(self):
        """Same state as a fresh install: the Grid column shows a dash and the
        report is otherwise unchanged. Refusing to open the tool over a
        scratch file would be the worse failure."""
        for junk in ("{not json", "[]", '{"projects": 4}', ""):
            with self.subTest(junk=junk):
                report_store.GRIDS_PATH.write_text(junk, encoding="utf-8")
                self.assertEqual(report_store.load_grids()["projects"], {})

    def test_an_absurdly_large_file_is_not_read_into_memory(self):
        report_store.GRIDS_PATH.write_text(
            " " * (report_store.MAX_GRIDS_BYTES + 10), encoding="utf-8")
        self.assertEqual(report_store.load_grids()["projects"], {})


class GridRoute(unittest.TestCase):
    """The endpoint the picker reaches, through the real Flask app."""

    @classmethod
    def setUpClass(cls):
        from server import app, API_REQUEST_HEADER
        app.config.update(TESTING=True)
        cls.client = app.test_client()
        cls.header = {API_REQUEST_HEADER: "1"}

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-grid-route-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        report_store.REPORT_DIR = self.tmp
        report_store.GRIDS_PATH = self.tmp / "grids.json"
        self.addCleanup(setattr, report_store, "REPORT_DIR",
                        report_store.SETTINGS_DIR / "report")
        self.addCleanup(setattr, report_store, "GRIDS_PATH",
                        report_store.SETTINGS_DIR / "report" / "grids.json")

    def post(self, action, payload):
        return self.client.post(f"/api/report/grid/{action}", json=payload,
                                headers=self.header)

    def test_save_then_get(self):
        r = self.post("save", {"projectId": PROJECT, "floorId": FLOOR_A,
                               "grid": a_grid()})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.get_json()["ok"], r.get_json())

        r = self.post("get", {"projectId": PROJECT})
        self.assertEqual(r.get_json()["floors"][FLOOR_A]["lettersAxis"], "x")

    def test_clear_through_the_route(self):
        self.post("save", {"projectId": PROJECT, "floorId": FLOOR_A,
                           "grid": a_grid()})
        self.post("clear", {"projectId": PROJECT, "floorId": FLOOR_A})
        self.assertEqual(self.post("get", {"projectId": PROJECT}).get_json()["floors"], {})

    def test_a_refusal_comes_back_as_a_sentence_and_not_a_traceback(self):
        r = self.post("save", {"projectId": PROJECT, "floorId": FLOOR_A,
                               "grid": {"a": {"x": "over there"}}})
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertFalse(body["ok"])
        self.assertTrue(body["error"])
        self.assertNotIn("Traceback", body["error"])

    def test_an_unknown_action_is_rejected(self):
        r = self.post("wipe", {"projectId": PROJECT})
        self.assertEqual(r.status_code, 404)

    def test_an_empty_body_does_not_raise(self):
        for action in ("get", "save", "clear"):
            with self.subTest(action=action):
                r = self.client.post(f"/api/report/grid/{action}",
                                     headers=self.header)
                self.assertIn(r.status_code, (200, 400))
                self.assertNotIn("Traceback", r.get_data(as_text=True))
