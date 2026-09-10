"""One load and one save, and the steps in the order that keeps them working.

The order is the whole risk here. Trimming unions every coordinate on a floor
into the crop box so that nothing ends up off the image, and a requirement area
is a coordinate carrier. Inject the area first and it holds the crop open; on a
fresh plan with no walls the area falls back to the whole canvas, so it holds
the crop open to the full sheet and the trimmer reports a tidy skip for a crop
it was prevented from making. Nothing about the result looks wrong.

So this file tests the order two ways. `OrderIsEnforced` checks the guard, and
`OrderIsEnforcedByBehaviour` builds the exact project that fails and asserts the
trim actually happened - that one fails if the steps run in the wrong sequence
even with every guard deleted.
"""
from __future__ import annotations

import io
import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import capacity_profiles, esx_trimmer, prep_pipeline  # noqa: E402

try:
    from PIL import Image
except ImportError:  # pragma: no cover - the trimmer needs it too
    Image = None


W, H = 800, 600
INK = (120, 90, 240, 180)          # a drawing in the middle, room to crop


def plan_image() -> bytes:
    im = Image.new("RGB", (W, H), "white")
    for x in range(INK[0], INK[2]):
        for y in range(INK[1], INK[3]):
            if x in (INK[0], INK[2] - 1) or y in (INK[1], INK[3] - 1):
                im.putpixel((x, y), (0, 0, 0))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def wall_type(name, attenuation=5.0):
    return {
        "name": name, "key": name, "color": "#B07842",
        "propagationProperties": [
            {"band": b, "attenuationFactor": attenuation,
             "reflectionCoefficient": 0.25, "diffractionCoefficient": 11}
            for b in ("TWO", "FIVE", "SIX")],
        "thickness": 0.1, "lowerEdge": 0,
        "id": "id-" + name.lower().replace(" ", "-"),
    }


def _chain(member, collection, obj):
    return [{"member": member, "collection": collection, "obj": obj}]


TEMPLATE = {
    "name": "Office",
    "requirementName": "WD Requirement",
    "items": [{"device": "Laptop", "usage": "Office", "perOccupant": 1},
              {"device": "Phone", "usage": "Office", "perOccupant": 2}],
    "profileDefs": {
        "devices": {
            "Laptop": _chain("deviceProfiles.json", "deviceProfiles",
                             {"id": "dev-laptop", "name": "Laptop"}),
            "Phone": _chain("deviceProfiles.json", "deviceProfiles",
                            {"id": "dev-phone", "name": "Phone"}),
        },
        "usages": {
            "Office": _chain("usageProfiles.json", "usageProfiles",
                             {"id": "use-office", "name": "Office"}),
        },
        "requirement": _chain("requirements.json", "requirements",
                              {"id": "req-wd", "name": "WD Requirement"}),
    },
}

#: Rows the project does not have and the template does not carry, which is
#: the one thing the capacity writer refuses outright.
UNRESOLVABLE = {"name": "Broken", "requirementName": "Nowhere",
                "items": [{"device": "Nothing Has This", "usage": "Office",
                           "perOccupant": 1}]}


def make_esx(path: Path, walls=False, areas=None):
    """A one-floor project whose plan has room to be cropped."""
    img = plan_image()
    members = {
        "project.json": {"project": {"name": "Fixture"}},
        "floorPlans.json": {"floorPlans": [{
            "id": "f1", "name": "Floor 1", "width": W, "height": H,
            "imageId": "img1", "metersPerUnit": 0.05,
            "cropMinX": 0, "cropMinY": 0, "cropMaxX": W, "cropMaxY": H,
        }]},
        "wallTypes.json": {"wallTypes": [wall_type("Concrete", 30.0)]},
        "wallSegments.json": {"wallSegments": []},
        "wallPoints.json": {"wallPoints": []},
        "accessPoints.json": {"accessPoints": []},
        "areas.json": {"areas": list(areas or [])},
    }
    if walls:
        # A rectangle of drawn wall, well inside the plan.
        pts = [(200, 150), (600, 150), (600, 450), (200, 450)]
        members["wallPoints.json"]["wallPoints"] = [
            {"id": f"wp{i}", "location": {"floorPlanId": "f1",
                                          "coord": {"x": x, "y": y}}}
            for i, (x, y) in enumerate(pts)]
        members["wallSegments.json"]["wallSegments"] = [
            {"id": f"ws{i}", "wallTypeId": "id-concrete",
             "wallPoints": [f"wp{i}", f"wp{(i + 1) % 4}"]}
            for i in range(4)]

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, body in members.items():
            z.writestr(name, json.dumps(body))
        z.writestr("image-img1", img)
    return path


def read(path, member):
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read(member))


def canvas_area(floor_w=W, floor_h=H, area_id="area-old"):
    """A requirement area covering the whole plan - what the pass produces
    when there is nothing on the floor to measure."""
    return {
        "id": area_id, "floorPlanId": "f1", "name": "Office",
        "requirementId": "req-wd", "color": "#2c3e50", "noteIds": [],
        "capacityItems": [{"identifier": "ci1", "deviceCount": 10,
                           "usageProfileId": "use-office",
                           "deviceProfileId": "dev-laptop"}],
        "area": [{"x": 0, "y": 0}, {"x": floor_w, "y": 0},
                 {"x": floor_w, "y": floor_h}, {"x": 0, "y": floor_h}],
    }


class OrderIsEnforced(unittest.TestCase):
    """The guard, checked directly."""

    def test_the_steps_come_back_in_the_declared_order(self):
        self.assertEqual(prep_pipeline.resolve_steps(["walls", "areas", "trim"]),
                         ["trim", "areas", "walls"])
        self.assertEqual(prep_pipeline.resolve_steps(["walls", "trim"]),
                         ["trim", "walls"])

    def test_an_unknown_step_is_refused_rather_than_ignored(self):
        with self.assertRaises(ValueError):
            prep_pipeline.resolve_steps(["trim", "paint"])

    def test_a_sequence_that_would_break_a_step_is_refused(self):
        with self.assertRaises(prep_pipeline.PrepOrderError):
            prep_pipeline._check_order(["areas", "trim", "walls"])
        # and it says why, in the report the operator would read
        try:
            prep_pipeline._check_order(["areas", "trim"])
        except prep_pipeline.PrepOrderError as exc:
            self.assertIn("holds the crop open", str(exc))

    def test_reordering_the_declared_order_fails_loudly(self):
        """The rules are checked against the sequence, not against the list
        that produced it - so editing STEP_ORDER cannot quietly break this."""
        original = prep_pipeline.STEP_ORDER
        prep_pipeline.STEP_ORDER = ("areas", "trim", "walls")
        try:
            with self.assertRaises(prep_pipeline.PrepOrderError):
                prep_pipeline.resolve_steps(None)
        finally:
            prep_pipeline.STEP_ORDER = original

    def test_every_rule_is_satisfied_by_the_declared_order(self):
        seq = list(prep_pipeline.STEP_ORDER)
        for earlier, later, why in prep_pipeline.ORDER_RULES:
            with self.subTest(rule=(earlier, later)):
                self.assertLess(seq.index(earlier), seq.index(later))
                self.assertTrue(why.strip(), "a rule with no reason is a note")


@unittest.skipIf(Image is None, "Pillow is required to trim a floor plan")
class OrderIsEnforcedByBehaviour(unittest.TestCase):
    """The order proved by what comes out, not by what the guard says.

    Delete every guard in the module and these still fail.
    """

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-prep-t-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_an_area_injected_first_would_stop_the_trim(self):
        """The failure this pipeline exists to make impossible.

        Not a test of the pipeline - a test that the hazard is real, so that
        the test below is measuring something.
        """
        esx = make_esx(self.tmp / "AreaFirst.esx", areas=[canvas_area()])
        report = esx_trimmer.analyze(esx)
        self.assertEqual(report.trimmed_count, 0)
        self.assertIn("fills", report.floors[0].reason)

    def test_the_pass_trims_the_floor_it_is_also_putting_an_area_on(self):
        esx = make_esx(self.tmp / "Project.esx")
        out = prep_pipeline.run(esx, steps=["trim", "areas", "walls"],
                                template=TEMPLATE, occupants=40,
                                wall_types=[wall_type("Framery Pod")])
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["ran"], ["trim", "areas", "walls"])
        self.assertTrue(out["written"])

        floor = read(esx, "floorPlans.json")["floorPlans"][0]
        self.assertLess(floor["width"], W,
                        "the floor was never cropped - the area held it open")
        self.assertEqual(out["step"]["trim"]["floors"][0]["action"], "trimmed")

    def test_the_area_is_measured_on_the_trimmed_canvas(self):
        """Each step reads what the one before it produced. If they were run
        against the original file the area would be sized for a canvas that no
        longer exists, and would hang off the edge of the plan."""
        esx = make_esx(self.tmp / "Project.esx")
        out = prep_pipeline.run(esx, steps=["trim", "areas"],
                                template=TEMPLATE, occupants=40)
        self.assertTrue(out["ok"], out)
        floor = read(esx, "floorPlans.json")["floorPlans"][0]
        area = read(esx, "areas.json")["areas"][0]
        for point in area["area"]:
            self.assertLessEqual(point["x"], floor["width"] + 0.5)
            self.assertLessEqual(point["y"], floor["height"] + 0.5)

    def test_running_the_steps_backwards_is_refused_before_anything_is_written(self):
        esx = make_esx(self.tmp / "Project.esx")
        before = esx.read_bytes()
        original = prep_pipeline.STEP_ORDER
        prep_pipeline.STEP_ORDER = ("areas", "trim")
        try:
            out = prep_pipeline.run(esx, template=TEMPLATE, occupants=40)
        finally:
            prep_pipeline.STEP_ORDER = original
        self.assertFalse(out["ok"])
        self.assertIn("must run before", out["error"])
        self.assertEqual(esx.read_bytes(), before, "the project was written to")


@unittest.skipIf(Image is None, "Pillow is required to trim a floor plan")
class OnePassOneSave(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-prep-o-"))
        self.esx = make_esx(self.tmp / "Project.esx")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_one_backup_for_the_whole_pass_not_one_per_step(self):
        prep_pipeline.run(self.esx, steps=["trim", "areas", "walls"],
                          template=TEMPLATE, occupants=40,
                          wall_types=[wall_type("Framery Pod")])
        backups = [p for p in self.tmp.iterdir() if p.name != "Project.esx"]
        self.assertEqual(len(backups), 1, [p.name for p in backups])
        self.assertEqual(read(backups[0], "floorPlans.json")["floorPlans"][0]["width"], W,
                         "the backup is not the original")

    def test_a_destination_leaves_the_source_alone(self):
        dest = self.tmp / "Prepared.esx"
        out = prep_pipeline.run(self.esx, dest=dest, steps=["walls"],
                                wall_types=[wall_type("Framery Pod")])
        self.assertTrue(out["ok"], out)
        self.assertEqual(len(read(self.esx, "wallTypes.json")["wallTypes"]), 1)
        self.assertEqual(len(read(dest, "wallTypes.json")["wallTypes"]), 2)

    def test_a_step_that_refuses_leaves_the_project_untouched(self):
        before = self.esx.read_bytes()
        out = prep_pipeline.run(self.esx, steps=["trim", "areas"],
                                template=UNRESOLVABLE, occupants=10)
        self.assertFalse(out["ok"], out)
        self.assertEqual(self.esx.read_bytes(), before)

    def test_the_preview_names_the_same_steps_the_run_will_take(self):
        preview = prep_pipeline.plan(self.esx, steps=["walls", "trim"],
                                     wall_types=[wall_type("Framery Pod")])
        out = prep_pipeline.run(self.esx, steps=["walls", "trim"],
                                wall_types=[wall_type("Framery Pod")])
        self.assertEqual(preview["steps"], out["ran"])

    def test_the_preview_writes_nothing(self):
        before = self.esx.read_bytes()
        prep_pipeline.plan(self.esx, template=TEMPLATE, occupants=40,
                           wall_types=[wall_type("Framery Pod")])
        self.assertEqual(self.esx.read_bytes(), before)


@unittest.skipIf(Image is None, "Pillow is required to trim a floor plan")
class RunningItAgain(unittest.TestCase):
    """He runs this, draws walls in Ekahau, and runs it again."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-prep-r-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_second_identical_run_changes_nothing_and_writes_nothing(self):
        esx = make_esx(self.tmp / "Project.esx")
        kw = dict(steps=["trim", "areas", "walls"], template=TEMPLATE,
                  occupants=40, wall_types=[wall_type("Framery Pod")])
        first = prep_pipeline.run(esx, **kw)
        self.assertTrue(first["written"], first)
        after_first = esx.read_bytes()

        second = prep_pipeline.run(esx, **kw)
        self.assertTrue(second["ok"], second)
        self.assertFalse(second["changed"], second.get("step"))
        self.assertFalse(second["written"])
        self.assertEqual(esx.read_bytes(), after_first)

    def test_an_area_that_covers_the_whole_plan_tightens_once_walls_exist(self):
        """The reason to run it a second time at all."""
        floor_w, floor_h = W, H
        esx = make_esx(self.tmp / "Project.esx", walls=True,
                       areas=[canvas_area(floor_w, floor_h)])
        out = prep_pipeline.run(esx, steps=["areas"], template=TEMPLATE,
                                occupants=40)
        self.assertTrue(out["ok"], out)
        self.assertEqual([s["newBasis"] for s in out["step"]["retighten"]], ["walls"])
        areas = read(esx, "areas.json")["areas"]
        self.assertEqual(len(areas), 1, "the old area was left behind as well")
        xs = [p["x"] for p in areas[0]["area"]]
        self.assertGreater(min(xs), 0, "the area still starts at the canvas edge")
        self.assertLess(max(xs), floor_w, "the area still runs to the canvas edge")

    def test_a_polygon_he_drew_is_never_replaced(self):
        """Anything that is not exactly the canvas rectangle is his work."""
        drawn = canvas_area()
        drawn["area"] = [{"x": 100, "y": 100}, {"x": 500, "y": 120},
                         {"x": 480, "y": 400}, {"x": 90, "y": 380}]
        esx = make_esx(self.tmp / "Project.esx", walls=True, areas=[drawn])
        out = prep_pipeline.run(esx, steps=["areas"], template=TEMPLATE,
                                occupants=40)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["step"]["retighten"], [])
        areas = read(esx, "areas.json")["areas"]
        self.assertEqual(len(areas), 1)
        self.assertEqual(areas[0]["area"], drawn["area"])

    def test_a_whole_plan_area_stays_when_there_is_still_nothing_to_measure(self):
        """Replacing it with an identical one is not progress."""
        esx = make_esx(self.tmp / "Project.esx", areas=[canvas_area()])
        out = prep_pipeline.run(esx, steps=["areas"], template=TEMPLATE,
                                occupants=40)
        self.assertTrue(out["ok"], out)
        self.assertEqual(out["step"]["retighten"], [])
        self.assertFalse(out["written"])
        self.assertEqual(len(read(esx, "areas.json")["areas"]), 1)

    def test_the_recogniser_only_admits_the_canvas_rectangle(self):
        floor = {"id": "f1", "width": W, "height": H}
        whole = canvas_area()["area"]
        self.assertTrue(prep_pipeline._is_canvas_rectangle(whole, floor))
        self.assertFalse(prep_pipeline._is_canvas_rectangle(
            [{"x": 6, "y": 6}, {"x": W, "y": 0}, {"x": W, "y": H}, {"x": 0, "y": H}],
            floor), "a nudged corner is a hand-edited polygon")
        self.assertFalse(prep_pipeline._is_canvas_rectangle(whole[:3], floor))
        self.assertFalse(prep_pipeline._is_canvas_rectangle(None, floor))
        self.assertFalse(prep_pipeline._is_canvas_rectangle(
            whole, {"id": "f1", "width": 0, "height": 0}))


class Refusals(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-prep-x-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_a_missing_project_is_refused_by_both(self):
        absent = self.tmp / "gone.esx"
        self.assertFalse(prep_pipeline.plan(absent)["ok"])
        self.assertFalse(prep_pipeline.run(absent)["ok"])

    def test_a_step_with_nothing_to_work_from_is_named(self):
        esx = make_esx(self.tmp / "Project.esx") if Image else None
        if esx is None:
            self.skipTest("Pillow is required to build the fixture")
        out = prep_pipeline.run(esx, steps=["walls"])
        self.assertFalse(out["ok"])
        self.assertIn("wall template", out["error"])
        out = prep_pipeline.run(esx, steps=["areas"])
        self.assertFalse(out["ok"])
        self.assertIn("capacity template", out["error"])


if __name__ == "__main__":
    unittest.main()
