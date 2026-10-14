"""An area drawn on the plan is the area that gets written.

Prep and Capacity both let the requirement area be drawn by hand instead of
measured from the walls. The back end owns three questions:

* what is accepted - three corners, a real size, no crossing edges;
* where it goes - into the area already on the floor, as a new area when there
  is none, and never onto a floor the run is leaving alone;
* where it lands after a trim - Prep draws on the plan as opened and the trim
  moves every coordinate, so the outline has to move with it.

The wording of the refusals is the page's, word for word:
`tests/test_area_editor.py` runs both sides on the same shapes.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tools import capacity_profiles as cap  # noqa: E402
from tools import prep_pipeline  # noqa: E402
from test_capacity_profiles import FLOOR, build_esx  # noqa: E402
import test_prep_pipeline as pp  # noqa: E402

RECT = [[300, 200], [900, 200], [900, 700], [300, 700]]
L_SHAPE = [[300, 200], [900, 200], [900, 400], [600, 400], [600, 700], [300, 700]]


def areas_of(path):
    with zipfile.ZipFile(path) as zf:
        return json.loads(zf.read("areas.json").decode("utf-8"))["areas"]


class WhatIsAccepted(unittest.TestCase):
    def test_a_real_outline_has_no_problem(self):
        self.assertEqual(cap.polygon_problem([tuple(p) for p in L_SHAPE]), "")

    def test_fewer_than_three_corners(self):
        self.assertEqual(cap.polygon_problem([(0, 0), (50, 50)]),
                         "An area needs at least three corners.")

    def test_a_sliver_is_too_small(self):
        self.assertEqual(cap.polygon_problem([(0, 0), (100, 0), (100, 3)]),
                         "That area is too small.")
        # three corners on a line enclose nothing at all
        self.assertEqual(cap.polygon_problem([(0, 0), (50, 0), (100, 0)]),
                         "That area is too small.")

    def test_a_bow_tie_crosses_itself(self):
        self.assertEqual(cap.polygon_problem([(0, 0), (100, 100), (100, 0), (0, 100)]),
                         "The outline crosses itself.")

    def test_clean_holds_corners_inside_the_floor_and_names_what_it_refused(self):
        floors = [{"id": "a", "width": 1000, "height": 500},
                  {"id": "b", "width": 1000, "height": 500}]
        good, bad = cap.clean_floor_areas(json.dumps({
            "a": [[-50, -50], [2000, 0], [2000, 900], [0, 900]],
            "b": [[0, 0], [10, 10]],
            "gone": [[0, 0], [100, 0], [100, 100]]}), floors)
        self.assertEqual([(p["x"], p["y"]) for p in good["a"]],
                         [(0, 0), (1000, 0), (1000, 500), (0, 500)])
        self.assertEqual(bad, {"b": "An area needs at least three corners."})

    def test_unreadable_input_is_nothing_not_a_crash(self):
        floors = [{"id": "a", "width": 1000, "height": 500}]
        for raw in ("{not json", "[]", None, '{"a": "x"}', '{"a": [[1, "z"], [2, 3], [4, 5]]}'):
            good, _bad = cap.clean_floor_areas(raw, floors)
            self.assertEqual(good, {}, raw)


class WhereItGoes(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        got = cap.extract(Path(build_esx(self.dir / "src.esx")))
        self.template = cap.derive_template(got, 500, "Office")

    def tearDown(self):
        self.tmp.cleanup()

    def project(self, name, areas):
        return Path(build_esx(self.dir / name, areas=areas))

    def plan(self, esx, drawn, **kw):
        return cap.plan_application(esx, self.template, 200,
                                    floor_areas=json.dumps({FLOOR: drawn}), **kw)

    def test_a_floor_with_nothing_drawn_gets_the_area_he_drew(self):
        esx = self.project("empty.esx", [])
        out = cap.apply_to(esx, self.dir / "o.esx", self.template, 200,
                           floor_areas=json.dumps({FLOOR: RECT}))
        self.assertTrue(out["ok"])
        self.assertEqual(out["areasDrawn"], 1)
        (area,) = areas_of(self.dir / "o.esx")
        self.assertEqual([(p["x"], p["y"]) for p in area["area"]],
                         [tuple(map(float, p)) for p in RECT])
        self.assertTrue(area["capacityItems"])

    def test_the_plan_describes_it_in_the_page_terms(self):
        esx = self.project("empty.esx", [])
        f = self.plan(esx, L_SHAPE)["floors"][0]
        self.assertTrue(f["drawn"])
        self.assertEqual(f["basis"], "drawn")
        self.assertEqual(f["action"], "create the area you drew")
        self.assertEqual(len(f["outline"]), 6)
        # figures come from the outline, not from the walls
        self.assertEqual(f["widthM"], round(600 * 0.05, 2))
        self.assertLess(f["areaSqFt"], f["widthFt"] * f["heightFt"])

    def test_an_area_already_on_the_floor_takes_his_outline_and_keeps_its_name(self):
        esx = self.project("has.esx", [
            {"id": "his", "name": "Warehouse", "floorPlanId": FLOOR,
             "requirementId": "req-1",
             "area": [{"x": 10, "y": 10}, {"x": 90, "y": 10}, {"x": 90, "y": 90}]}])
        out = cap.apply_to(esx, self.dir / "o.esx", self.template, 200,
                           floor_areas=json.dumps({FLOOR: RECT}))
        self.assertTrue(out["ok"])
        (area,) = areas_of(self.dir / "o.esx")
        self.assertEqual(area["id"], "his")
        self.assertEqual(area["name"], "Warehouse")
        self.assertEqual(len(area["area"]), 4)
        self.assertEqual(area["area"][2], {"x": 900.0, "y": 700.0})

    def test_without_a_drawn_outline_his_own_outline_is_still_left_alone(self):
        mine = [{"x": 10, "y": 10}, {"x": 90, "y": 10}, {"x": 90, "y": 90}]
        esx = self.project("has.esx", [
            {"id": "his", "name": "W", "floorPlanId": FLOOR,
             "requirementId": "req-1", "area": mine}])
        cap.apply_to(esx, self.dir / "o.esx", self.template, 200)
        self.assertEqual(areas_of(self.dir / "o.esx")[0]["area"], mine)

    def test_a_floor_told_to_keep_its_devices_ignores_the_drawing_and_says_so(self):
        counted = [{"identifier": "i", "deviceCount": 5,
                    "usageProfileId": "use-normal", "deviceProfileId": "dev-laptop"}]
        keep_area = [{"x": 1, "y": 1}, {"x": 50, "y": 1}, {"x": 50, "y": 50}]
        esx = self.project("full.esx", [
            {"id": "x", "floorPlanId": FLOOR, "requirementId": "req-1",
             "capacityItems": counted, "area": keep_area}])
        f = self.plan(esx, RECT, existing="keep")["floors"][0]
        self.assertTrue(f["skipped"])
        self.assertTrue(f["drawnUnused"])
        self.assertIn("keeps its existing", f["drawnUnusedWhy"])
        self.assertNotIn("drawn", f)
        out = cap.apply_to(esx, self.dir / "o.esx", self.template, 200,
                           existing="keep", floor_areas=json.dumps({FLOOR: RECT}))
        self.assertEqual(out["areasDrawn"], 0)

    def test_replacing_devices_uses_the_drawing_instead_of_keeping_the_outline(self):
        counted = [{"identifier": "i", "deviceCount": 5,
                    "usageProfileId": "use-normal", "deviceProfileId": "dev-laptop"}]
        esx = self.project("full.esx", [
            {"id": "x", "floorPlanId": FLOOR, "requirementId": "req-1",
             "capacityItems": counted,
             "area": [{"x": 1, "y": 1}, {"x": 50, "y": 1}, {"x": 50, "y": 50}]}])
        out = cap.apply_to(esx, self.dir / "o.esx", self.template, 200,
                           existing="devices", floor_areas=json.dumps({FLOOR: RECT}))
        self.assertEqual(out["areasDrawn"], 1)
        self.assertEqual(len(areas_of(self.dir / "o.esx")[0]["area"]), 4)

    def test_a_refused_outline_goes_back_to_automatic_and_is_named(self):
        esx = self.project("empty.esx", [])
        f = self.plan(esx, [[0, 0], [10, 10]])["floors"][0]
        self.assertNotIn("drawn", f)
        self.assertEqual(f["drawnProblem"], "An area needs at least three corners.")
        self.assertNotEqual(f["basis"], "drawn")


class AfterATrim(unittest.TestCase):
    """Prep draws on the plan as it was opened; the trim moves everything."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.esx = pp.make_esx(self.dir / "in.esx")
        self.box = [100, 80, 700, 480]

    def tearDown(self):
        self.tmp.cleanup()

    def run_prep(self, steps, drawn):
        return prep_pipeline.run(
            str(self.esx), dest=self.dir / "out.esx", steps=steps,
            template=pp.TEMPLATE, occupants=100, boxes={"f1": self.box},
            floor_areas=json.dumps({"f1": drawn}))

    def test_the_outline_moves_with_the_crop(self):
        out = self.run_prep(["trim", "areas"], [[200, 150], [600, 150], [600, 450], [200, 450]])
        self.assertTrue(out["ok"], out)
        (area,) = pp.read(self.dir / "out.esx", "areas.json")["areas"]
        self.assertEqual([(p["x"], p["y"]) for p in area["area"]],
                         [(100, 70), (500, 70), (500, 370), (100, 370)])

    def test_without_a_trim_it_is_written_where_it_was_drawn(self):
        out = self.run_prep(["areas"], [[200, 150], [600, 150], [600, 450], [200, 450]])
        self.assertTrue(out["ok"], out)
        (area,) = pp.read(self.dir / "out.esx", "areas.json")["areas"]
        self.assertEqual(area["area"][0], {"x": 200.0, "y": 150.0})

    def test_a_corner_outside_the_crop_is_held_on_its_edge_and_reported(self):
        out = self.run_prep(["trim", "areas"], [[50, 150], [600, 150], [600, 450], [50, 450]])
        self.assertTrue(out["ok"], out)
        (area,) = pp.read(self.dir / "out.esx", "areas.json")["areas"]
        self.assertEqual(area["area"][0]["x"], 0)
        self.assertEqual(out["step"]["trim"]["drawnAreasHeldOnEdge"], ["f1"])

    def test_the_helper_leaves_a_floor_the_trim_did_not_touch_alone(self):
        class Floor:
            def __init__(self, fid, offset, new_size):
                self.floor_id, self.offset, self.new_size = fid, offset, new_size

        class Report:
            floors = [Floor("a", (10, 20), (100, 100)), Floor("b", None, None)]

        drawn = {"a": [[110, 120], [20, 30], [50, 90]], "b": [[1, 2], [3, 4], [5, 6]]}
        moved, held = prep_pipeline.shift_floor_areas(drawn, Report())
        self.assertEqual(moved["b"], drawn["b"])
        self.assertEqual(moved["a"][0], {"x": 100.0, "y": 100.0})
        self.assertEqual(held, [])

    def test_the_preview_names_the_drawn_area_too(self):
        out = prep_pipeline.plan(
            str(self.esx), steps=["areas"], template=pp.TEMPLATE, occupants=100,
            floor_areas=json.dumps({"f1": [[200, 150], [600, 150], [600, 450]]}))
        floor = out["step"]["areas"]["floors"][0]
        self.assertTrue(floor["drawn"])
        self.assertEqual(out["step"]["areas"]["drawnUsed"], 1)


class OverAPlaceholder(unittest.TestCase):
    """An area covering the whole plan is re-measured by a run; drawing one
    on that floor says what he wants instead, so the run uses it."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.esx = pp.make_esx(self.dir / "in.esx", walls=True, areas=[pp.canvas_area()])
        self.drawn = [[250, 200], [550, 200], [550, 400], [250, 400]]

    def tearDown(self):
        self.tmp.cleanup()

    def test_the_preview_says_it_will_be_replaced_by_the_drawing(self):
        out = prep_pipeline.plan(
            str(self.esx), steps=["areas"], template=pp.TEMPLATE, occupants=100,
            floor_areas=json.dumps({"f1": self.drawn}))
        (floor,) = out["step"]["areas"]["floors"]
        self.assertFalse(floor["skipped"])
        self.assertTrue(floor["drawn"])
        self.assertEqual(floor["basis"], "drawn")
        self.assertEqual([(p["x"], p["y"]) for p in floor["outline"]],
                         [tuple(map(float, p)) for p in self.drawn])
        self.assertIn("the one you drew", floor["action"])

    def test_the_run_writes_the_drawing_and_no_second_area(self):
        out = prep_pipeline.run(
            str(self.esx), dest=self.dir / "o.esx", steps=["areas"],
            template=pp.TEMPLATE, occupants=100,
            floor_areas=json.dumps({"f1": self.drawn}))
        self.assertTrue(out["ok"], out)
        (area,) = pp.read(self.dir / "o.esx", "areas.json")["areas"]
        self.assertEqual([(p["x"], p["y"]) for p in area["area"]],
                         [tuple(map(float, p)) for p in self.drawn])

    def test_the_helper_that_swaps_the_outline_in_replaces_the_figures_too(self):
        info = {"floorPlanId": "f", "basis": "walls", "widthFt": 1, "heightFt": 1,
                "areaSqFt": 1, "padMeters": 0.5, "polygon": [], "skipped": True,
                "drawnUnused": True}
        floor = {"id": "f", "width": 800, "height": 600, "metersPerUnit": 0.05}
        poly = [{"x": 0, "y": 0}, {"x": 400, "y": 0}, {"x": 400, "y": 200}, {"x": 0, "y": 200}]
        cap.apply_drawn_outline(info, floor, poly)
        self.assertEqual((info["basis"], info["padMeters"]), ("drawn", 0.0))
        self.assertNotIn("drawnUnused", info)
        self.assertEqual((info["widthM"], info["heightM"]), (20.0, 10.0))
        self.assertEqual(info["areaSqFt"], round(20 * 10 / 0.3048 ** 2, 1))
        self.assertEqual(info["fractionOfCanvas"], round(400 * 200 / (800 * 600), 4))


class TheRoutesCarryIt(unittest.TestCase):
    """`floorAreas` on the query string reaches the writer, on both servers'
    routes, and what comes back says it was used."""

    def setUp(self):
        import io
        import server
        from urllib.parse import quote, unquote
        self.io, self.quote, self.unquote = io, quote, unquote
        server.app.config["TESTING"] = True
        self.client = server.app.test_client()
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self._cap_dir, cap.USER_DIR = cap.USER_DIR, root / "capacity"
        cap.save_template(dict(pp.TEMPLATE))
        self.cap_file = cap.list_templates()["templates"][0]["_file"]
        self.drawn = json.dumps({"f1": [[200, 150], [600, 150], [600, 450], [200, 450]]})
        self.prep_bytes = pp.make_esx(root / "P.esx").read_bytes()
        self.hdr = {"X-WD-Wireless-Tools": "1"}

    def tearDown(self):
        cap.USER_DIR = self._cap_dir
        self.tmp.cleanup()

    def test_prep_plan_describes_the_drawn_area(self):
        res = self.client.post(
            "/api/prep/plan?steps=areas&capacityTemplate=%s&occupants=40&floorAreas=%s"
            % (self.cap_file, self.quote(self.drawn)),
            data=self.prep_bytes, headers=self.hdr, content_type="application/octet-stream")
        body = res.get_json()
        self.assertTrue(body["ok"], body)
        floor = body["step"]["areas"]["floors"][0]
        self.assertTrue(floor["drawn"])
        self.assertEqual(floor["outline"][2], {"x": 600.0, "y": 450.0})

    def test_prep_run_writes_it_and_the_summary_header_says_so(self):
        res = self.client.post(
            "/api/prep/run?name=P.esx&steps=areas&capacityTemplate=%s&occupants=40&floorAreas=%s"
            % (self.cap_file, self.quote(self.drawn)),
            data=self.prep_bytes, headers=self.hdr, content_type="application/octet-stream")
        self.assertEqual(res.status_code, 200)
        summary = json.loads(self.unquote(res.headers["X-WD-Prep-Report"]))
        self.assertEqual(summary["areasDrawn"], 1)
        with zipfile.ZipFile(self.io.BytesIO(res.data)) as z:
            (area,) = json.loads(z.read("areas.json"))["areas"]
        self.assertEqual(area["area"][2], {"x": 600.0, "y": 450.0})

    def test_capacity_plan_and_apply_use_it(self):
        raw = Path(build_esx(Path(self.tmp.name) / "C.esx", areas=[])).read_bytes()
        drawn = json.dumps({FLOOR: RECT})
        query = "?template=%s&occupants=40&floorAreas=%s" % (self.cap_file, self.quote(drawn))
        plan = self.client.post("/api/capacity/plan" + query, data=raw, headers=self.hdr)
        self.assertTrue(plan.get_json()["floors"][0]["drawn"])
        applied = self.client.post("/api/capacity/apply" + query, data=raw, headers=self.hdr)
        self.assertEqual(applied.status_code, 200, applied.data[:200])
        report = json.loads(self.unquote(applied.headers["X-WD-Capacity-Report"]))
        self.assertEqual(report["areasDrawn"], 1)
        with zipfile.ZipFile(self.io.BytesIO(applied.data)) as z:
            (area,) = json.loads(z.read("areas.json"))["areas"]
        self.assertEqual(area["area"][2], {"x": 900.0, "y": 700.0})


if __name__ == "__main__":
    unittest.main()
