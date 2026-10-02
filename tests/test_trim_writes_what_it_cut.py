"""What a crop leaves in the file is what the crop decided - every time.

Four defects, each found by building the project and reading the output, and
each one silent: the file opened, the floor was the expected size, and the
damage was somewhere nobody looks.

* A drawn box that cut the *only* object of its kind on a floor left that file
  untouched. A member was rewritten only when the offset moved something in
  it, and with the one AP cut there was nothing left to move - so the original
  bytes were copied through and the AP came back, uncut and off the plan,
  while its radio (in a file that *was* rewritten) was gone.
* The older single ``surveys.json`` was not recognised as survey data, so its
  route points were neither moved with the crop nor counted in its bounds.
* A box saved for the full-size original was reapplied to the "(prepared)"
  copy, which keeps the project id but has the smaller sheet. Clamped to that
  sheet it cropped the plan a second time and cut what had been placed since.
* With Trim and Areas and Re-measure in one Prep run, the whole-canvas
  placeholder area the areas step was about to replace held the trim open to
  the full sheet, and the trim skipped as "already fills 100%".

Every project here is invented.
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
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from tools import esx_trimmer, plantrim_store, prep_pipeline  # noqa: E402

try:
    from PIL import Image, ImageDraw
except ImportError:  # pragma: no cover - the trimmer needs it too
    Image = None

FLOOR = "flr-invented-1"
PROJECT = "prj-invented-review"


def _png(w, h, frame=None):
    im = Image.new("RGB", (w, h), "white")
    if frame:
        ImageDraw.Draw(im).rectangle(frame, outline="black", width=3)
    buf = io.BytesIO()
    im.save(buf, "PNG")
    return buf.getvalue()


def build(path: Path, w, h, members: dict, frame=None) -> Path:
    plan = {"id": FLOOR, "name": "Invented Floor", "imageId": "img-invented",
            "width": float(w), "height": float(h), "metersPerUnit": 0.05}
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("floorPlans.json", json.dumps({"floorPlans": [plan]}))
        z.writestr("image-img-invented", _png(w, h, frame))
        for name, body in members.items():
            z.writestr(name, json.dumps(body))
    return path


def read(path: Path, member: str):
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read(member))


def ap(ap_id, name, x, y):
    return {"id": ap_id, "name": name,
            "location": {"floorPlanId": FLOOR, "coord": {"x": x, "y": y}}}


class _Tmp(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-trim-writes-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)


@unittest.skipIf(Image is None, "Pillow is required to trim a floor plan")
class ACutObjectStaysCut(_Tmp):
    """The box keeps a wall in one corner and cuts the only AP, the only
    exclusion area and the only attenuation area, all far outside it."""

    def setUp(self):
        super().setUp()
        self.src = build(self.tmp / "in.esx", 1000, 800, {
            "accessPoints.json": {"accessPoints": [ap("ap-out", "Invented AP", 900, 700)]},
            "simulatedRadios.json": {"simulatedRadios": [
                {"id": "r-out", "accessPointId": "ap-out"}]},
            "exclusionAreas.json": {"exclusionAreas": [
                {"id": "x-out", "floorPlanId": FLOOR,
                 "area": [{"x": 850, "y": 650}, {"x": 950, "y": 650},
                          {"x": 950, "y": 750}]}]},
            "attenuationAreas.json": {"attenuationAreas": [
                {"id": "at-out", "floorPlanId": FLOOR,
                 "area": [{"x": 820, "y": 620}, {"x": 980, "y": 620},
                          {"x": 980, "y": 780}]}]},
            "wallPoints.json": {"wallPoints": [
                {"id": "w-in", "location": {"floorPlanId": FLOOR,
                                            "coord": {"x": 200, "y": 200}}}]},
        }, frame=(100, 100, 500, 400))
        self.out = self.tmp / "out.esx"
        self.report = esx_trimmer.trim(self.src, self.out,
                                       boxes={FLOOR: [100, 100, 500, 400]})

    def test_the_cut_objects_are_not_in_the_output(self):
        self.assertEqual(self.report.floors[0].action, "trimmed")
        self.assertEqual(read(self.out, "accessPoints.json")["accessPoints"], [])
        self.assertEqual(read(self.out, "exclusionAreas.json")["exclusionAreas"], [])
        self.assertEqual(read(self.out, "attenuationAreas.json")["attenuationAreas"], [])
        # and the radio went with its AP, as it already did
        self.assertEqual(read(self.out, "simulatedRadios.json")["simulatedRadios"], [])

    def test_nothing_in_the_output_is_off_the_plan(self):
        plan = read(self.out, "floorPlans.json")["floorPlans"][0]
        members = {n: read(self.out, n) for n in (
            "accessPoints.json", "exclusionAreas.json", "attenuationAreas.json",
            "wallPoints.json")}
        for c, kind, _name in esx_trimmer._floor_coords(members, FLOOR):
            with self.subTest(kind=kind):
                self.assertTrue(0 <= c["x"] <= plan["width"]
                                and 0 <= c["y"] <= plan["height"], (kind, c))

    def test_a_file_the_cut_did_not_touch_is_copied_byte_for_byte(self):
        """The fix writes what was cut, not everything: a cascade file with
        nothing to lose keeps its original bytes."""
        src = self.tmp / "keep.esx"
        build(src, 1000, 800, {
            "wallPoints.json": {"wallPoints": [
                {"id": "w-in", "location": {"floorPlanId": FLOOR,
                                            "coord": {"x": 200, "y": 200}}},
                {"id": "w-out", "location": {"floorPlanId": FLOOR,
                                             "coord": {"x": 900, "y": 700}}}]},
            "measuredRadios.json": {"measuredRadios": []},
        })
        out = self.tmp / "keep-out.esx"
        esx_trimmer.trim(src, out, boxes={FLOOR: [100, 100, 500, 400]})
        with zipfile.ZipFile(src) as a, zipfile.ZipFile(out) as b:
            self.assertEqual(a.read("measuredRadios.json"), b.read("measuredRadios.json"))
        self.assertEqual([p["id"] for p in read(out, "wallPoints.json")["wallPoints"]],
                         ["w-in"])


@unittest.skipIf(Image is None, "Pillow is required to trim a floor plan")
class TheOlderSurveyFileMovesWithTheCrop(_Tmp):
    """``surveys.json`` (one file for every walk) is survey data as much as
    ``survey-<id>.json`` is."""

    WALK = {"surveys": [{"id": "sv-invented", "floorPlanId": FLOOR,
                         "routePoints": [[{"location": {"x": 600, "y": 600}},
                                          {"location": {"x": 1500, "y": 1300}}]]}]}

    def test_route_points_are_moved_with_the_plan(self):
        src = build(self.tmp / "in.esx", 2000, 1600, {
            "accessPoints.json": {"accessPoints": [ap("ap-1", "Invented AP", 600, 600)]},
            "surveys.json": self.WALK,
        }, frame=(500, 500, 900, 800))
        out = self.tmp / "out.esx"
        rep = esx_trimmer.trim(src, out, margin="tight")
        f = rep.floors[0]
        self.assertEqual(f.action, "trimmed", f.reason)
        dx, dy = f.offset
        moved_ap = read(out, "accessPoints.json")["accessPoints"][0]["location"]["coord"]
        first = read(out, "surveys.json")["surveys"][0]["routePoints"][0][0]["location"]
        self.assertEqual((first["x"], first["y"]), (moved_ap["x"], moved_ap["y"]))
        self.assertEqual((first["x"], first["y"]), (600 - dx, 600 - dy))

    def test_the_walk_holds_the_crop_open(self):
        """The far end of the walk is beyond the drawing; the crop has to keep
        it on the plan rather than cut the sheet out from under it."""
        src = build(self.tmp / "in2.esx", 2000, 1600, {"surveys.json": self.WALK},
                    frame=(500, 500, 900, 800))
        f = esx_trimmer.analyze(src, margin="tight").floors[0]
        self.assertEqual(f.action, "trimmed", f.reason)
        x0, y0 = f.offset
        self.assertLessEqual(x0, 600)
        self.assertGreaterEqual(x0 + f.new_size[0], 1500)
        self.assertGreaterEqual(y0 + f.new_size[1], 1300)

    def test_a_drawn_box_cuts_the_points_outside_it(self):
        src = build(self.tmp / "in3.esx", 2000, 1600, {"surveys.json": self.WALK},
                    frame=(500, 500, 900, 800))
        out = self.tmp / "out3.esx"
        esx_trimmer.trim(src, out, boxes={FLOOR: [400, 400, 1000, 900]})
        legs = read(out, "surveys.json")["surveys"][0]["routePoints"]
        self.assertEqual(legs, [[{"location": {"x": 200.0, "y": 200.0}}]])


@unittest.skipIf(Image is None, "Pillow is required to trim a floor plan")
class APreparedCopyIsNotCroppedTwice(_Tmp):
    """Draw a box, prepare, place an AP in the prepared copy, prepare again."""

    BOX = [400, 300, 1600, 1200]

    def setUp(self):
        super().setUp()
        self._store = plantrim_store.STORE
        plantrim_store.STORE = self.tmp / "plantrim-boxes.json"
        self.addCleanup(setattr, plantrim_store, "STORE", self._store)

        self.src = build(self.tmp / "Invented.esx", 2000, 1500, {
            "project.json": {"project": {"id": PROJECT, "name": "Invented"}},
            "accessPoints.json": {"accessPoints": [ap("ap-a", "AP-A", 900, 700)]},
        }, frame=(400, 300, 1600, 1200))
        plantrim_store.save(PROJECT, {FLOOR: self.BOX})
        first = self.tmp / "Invented (prepared).esx"
        r = prep_pipeline.run(str(self.src), dest=str(first), steps=["trim"],
                              boxes={FLOOR: self.BOX})
        self.assertTrue(r["ok"], r)
        self.assertEqual(r["step"]["trim"]["floors"][0]["newSize"], [1200, 900])

        # An AP placed afterwards near the top-left of the kept plan - inside
        # the 1200x900 sheet, outside the old box's 400,300 corner.
        with zipfile.ZipFile(first) as z:
            raw = {n: z.read(n) for n in z.namelist()}
        aps = json.loads(raw["accessPoints.json"])
        aps["accessPoints"].append(ap("ap-b", "AP-B", 100, 100))
        raw["accessPoints.json"] = json.dumps(aps).encode()
        self.prepared = self.tmp / "edited.esx"
        with zipfile.ZipFile(self.prepared, "w") as z:
            for n, b in raw.items():
                z.writestr(n, b)

    def test_the_trimmer_refuses_a_box_that_does_not_fit_the_sheet(self):
        """Any caller: the old box overhangs the 1200x900 sheet."""
        out = self.tmp / "again.esx"
        rep = esx_trimmer.trim(self.prepared, out, boxes={FLOOR: self.BOX})
        f = rep.floors[0]
        self.assertEqual(f.action, "refused")
        self.assertIn("does not fit", f.reason)
        self.assertEqual(sorted(a["name"] for a in read(out, "accessPoints.json")["accessPoints"]),
                         ["AP-A", "AP-B"])
        self.assertEqual(read(out, "floorPlans.json")["floorPlans"][0]["width"], 1200.0)

    def test_box_fits_sheet_allows_a_pixel_and_no_more(self):
        fits = esx_trimmer.box_fits_sheet
        self.assertTrue(fits([0, 0, 1200, 900], 1200, 900))
        self.assertTrue(fits([-1, -1, 1201, 901], 1200, 900))
        self.assertTrue(fits([1200, 900, 0, 0], 1200, 900))      # reversed drag
        self.assertFalse(fits(self.BOX, 1200, 900))
        self.assertFalse(fits([-2, 0, 100, 100], 1200, 900))
        self.assertFalse(fits([0, 0, 100, 902], 1200, 900))
        self.assertTrue(fits(self.BOX, 0, 0))                    # size unknown
        self.assertFalse(fits(["a", 0, 1, 1], 1200, 900))

    def test_a_box_at_the_edge_is_still_taken(self):
        """A pixel of slack, as PlanTrim allows: a box dragged to the edge."""
        rep = esx_trimmer.analyze(self.prepared, boxes={FLOOR: [50, 50, 1201, 901]})
        self.assertEqual(rep.floors[0].action, "trimmed", rep.floors[0].reason)

    def test_the_server_sets_the_saved_box_aside(self):
        import server
        server.app.config["TESTING"] = True
        client = server.app.test_client()
        name = quote("Invented (prepared).esx")
        q = f"name={name}&steps=trim&margin=tight&useBoxes=1"
        hdr = {server.API_REQUEST_HEADER: "1"}

        r = client.post("/api/prep/plan?" + q, data=self.prepared.read_bytes(),
                        headers=hdr)
        body = r.get_json()
        self.assertTrue(body.get("ok"), body)
        self.assertEqual(body["project"]["boxes"], {})
        self.assertEqual(body["project"]["boxesSetAside"],
                         {FLOOR: [float(v) for v in self.BOX]})
        self.assertNotEqual(body["step"]["trim"]["floors"][0]["source"], "manual")

        r = client.post("/api/prep/run?" + q, data=self.prepared.read_bytes(),
                        headers=hdr)
        try:
            self.assertEqual(r.status_code, 200, r.get_data()[:300])
            # The prepared sheet is already cropped to its drawing, so the
            # automatic pass has nothing to do - and above all cuts nothing.
            body = r.get_json()
            f = body["step"]["trim"]["floors"][0]
            self.assertNotEqual(f["source"], "manual")
            self.assertEqual(f["droppedCount"], 0)
            self.assertFalse(body.get("written"))
        finally:
            r.close()

        # The box stays stored for the original it was drawn on.
        self.assertEqual(plantrim_store.load(PROJECT),
                         {FLOOR: [float(v) for v in self.BOX]})

    def test_the_original_still_gets_its_box(self):
        import server
        facts = server._prep_project_facts(self.src)
        self.assertEqual(facts["boxes"], {FLOOR: [float(v) for v in self.BOX]})
        self.assertEqual(facts["boxesSetAside"], {})


@unittest.skipIf(Image is None, "Pillow is required to trim a floor plan")
class APlaceholderAboutToBeReplacedDoesNotStopTheTrim(_Tmp):
    """Trim, Areas and Re-measure in one run, on a project whose requirement
    area is still the whole canvas and which now has walls to measure."""

    def setUp(self):
        super().setUp()
        from test_prep_pipeline import TEMPLATE, canvas_area, make_esx, W, H
        self.W, self.H, self.TEMPLATE = W, H, TEMPLATE
        self.src = make_esx(self.tmp / "in.esx", walls=True,
                            areas=[canvas_area()])
        self.out = self.tmp / "out.esx"

    def _run(self, **kw):
        args = dict(steps=["trim", "areas"], template=self.TEMPLATE,
                    occupants="20", margin="tight")
        args.update(kw)
        return prep_pipeline.run(str(self.src), dest=str(self.out), **args)

    def test_the_trim_happens(self):
        r = self._run()
        self.assertTrue(r["ok"], r)
        f = r["step"]["trim"]["floors"][0]
        self.assertEqual(f["action"], "trimmed", f["reason"])
        plan = read(self.out, "floorPlans.json")["floorPlans"][0]
        self.assertLess(plan["width"], self.W)

    def test_the_placeholder_is_replaced_and_nothing_is_off_the_plan(self):
        r = self._run()
        self.assertTrue(r["ok"], r)
        self.assertEqual([s["areaId"] for s in r["step"]["retighten"]], ["area-old"])
        plan = read(self.out, "floorPlans.json")["floorPlans"][0]
        areas = read(self.out, "areas.json")["areas"]
        self.assertNotIn("area-old", [a["id"] for a in areas])
        self.assertEqual(len(areas), 1)
        for c in areas[0]["area"]:
            self.assertTrue(0 <= c["x"] <= plan["width"] and 0 <= c["y"] <= plan["height"])
        # measured from the walls, not the canvas again
        self.assertFalse(prep_pipeline._is_canvas_rectangle(areas[0]["area"], plan))

    def test_the_preview_says_the_same(self):
        p = prep_pipeline.plan(str(self.src), steps=["trim", "areas"],
                               template=self.TEMPLATE, occupants="20",
                               margin="tight")
        self.assertEqual(p["step"]["trim"]["floors"][0]["action"], "trimmed")

    def test_if_the_areas_step_refuses_the_placeholder_is_kept_on_the_new_canvas(self):
        """The areas step is still all or nothing: what is left is a
        placeholder on the trimmed plan, not a floor with no area."""
        from test_prep_pipeline import UNRESOLVABLE
        r = self._run(template=UNRESOLVABLE)
        self.assertIn("areas", [f["step"] for f in r["failed"]])
        plan = read(self.out, "floorPlans.json")["floorPlans"][0]
        self.assertLess(plan["width"], self.W)
        areas = read(self.out, "areas.json")["areas"]
        self.assertEqual([a["id"] for a in areas], ["area-old"])
        self.assertTrue(prep_pipeline._is_canvas_rectangle(areas[0]["area"], plan))

    def test_without_re_measure_the_area_still_holds_the_crop(self):
        """Only an area this run will replace is set aside; otherwise the
        documented rule stands."""
        r = self._run(retighten=False)
        self.assertEqual(r["step"]["trim"]["floors"][0]["action"], "skipped")


if __name__ == "__main__":
    unittest.main()
