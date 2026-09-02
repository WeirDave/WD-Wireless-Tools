"""Tests for tools.esx_trimmer.

Fixtures are generated here rather than copied from real projects, but the
shapes they use were checked against 109 real Ekahau projects (173 floor
plans): coordinates live in full-image pixel space alongside the floor's own
crop rectangle, ``referencePoints`` carry a floorPlanId per projection, and
survey route points are a list of lists whose coordinate sits directly under
``location``.
"""
from __future__ import annotations

import io
import json
import unittest
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

from tools import esx_trimmer as trimmer

try:
    from PIL import Image
    HAVE_PILLOW = True
except ImportError:  # pragma: no cover - depends on environment
    HAVE_PILLOW = False

FLOOR_A = "10000000-0000-4000-8000-00000000000a"
FLOOR_B = "10000000-0000-4000-8000-00000000000b"
IMG_A = "20000000-0000-4000-8000-00000000000a"
IMG_B = "20000000-0000-4000-8000-00000000000b"

SCALE_A = 0.025125193199381765
SCALE_B = 0.026324440306060487


def _drawing(width=400, height=300, box=(120, 80, 260, 210), fmt="PNG"):
    """A blank canvas with a dark rectangle occupying part of it."""
    im = Image.new("RGB", (width, height), "white")
    for x in range(box[0], box[2]):
        for y in range(box[1], box[3]):
            if x in (box[0], box[2] - 1) or y in (box[1], box[3] - 1):
                im.putpixel((x, y), (10, 10, 10))
    buf = io.BytesIO()
    im.save(buf, format=fmt)
    return buf.getvalue()


def _plan(fid, image_id, w, h, scale, **extra):
    plan = {
        "id": fid,
        "name": f"Floor {fid[-1].upper()}",
        "width": float(w),
        "height": float(h),
        "metersPerUnit": scale,
        "imageId": image_id,
        "cropMinX": 0.0, "cropMinY": 0.0,
        "cropMaxX": float(w), "cropMaxY": float(h),
        "gpsReferencePoints": [],
    }
    plan.update(extra)
    return plan


def make_project(path: Path, *, plans=None, images=None, extra_members=None) -> Path:
    """Write a small .esx containing every coordinate-carrying shape."""
    if plans is None:
        plans = [
            _plan(FLOOR_A, IMG_A, 400, 300, SCALE_A),
            _plan(FLOOR_B, IMG_B, 400, 300, SCALE_B),
        ]
    if images is None:
        images = {IMG_A: _drawing(), IMG_B: _drawing()}

    members = {
        "project.json": {"project": {"id": "p1", "name": "Fixture"}},
        "floorPlans.json": {"floorPlans": plans},
        "accessPoints.json": {"accessPoints": [
            {"id": "ap1", "name": "AP-1",
             "location": {"floorPlanId": FLOOR_A, "coord": {"x": 150.0, "y": 100.0}}},
            {"id": "ap2", "name": "AP-2",
             "location": {"floorPlanId": FLOOR_B, "coord": {"x": 200.0, "y": 150.0}}},
        ]},
        "wallPoints.json": {"wallPoints": [
            {"id": "wp1", "location": {"floorPlanId": FLOOR_A, "coord": {"x": 130.0, "y": 90.0}}},
            {"id": "wp2", "location": {"floorPlanId": FLOOR_A, "coord": {"x": 250.0, "y": 200.0}}},
        ]},
        "areas.json": {"areas": [
            {"id": "a1", "floorPlanId": FLOOR_A,
             "area": [{"x": 140.0, "y": 95.0}, {"x": 240.0, "y": 95.0}, {"x": 240.0, "y": 195.0}]},
        ]},
        # One reference point projected onto BOTH floors, each projection
        # carrying its own floorPlanId and needing its own offset.
        "referencePoints.json": {"referencePoints": [
            {"id": "rp1", "name": "Alignment 1", "projections": [
                {"floorPlanId": FLOOR_A, "coord": {"x": 160.0, "y": 110.0}},
                {"floorPlanId": FLOOR_B, "coord": {"x": 210.0, "y": 160.0}},
            ]},
        ]},
        # routePoints is a list of lists and the coord sits directly under
        # `location`, not under `location.coord`.
        "survey-00000000-0000-4000-8000-000000000009.json": {"surveys": [
            {"id": "s1", "floorPlanId": FLOOR_A, "routePoints": [
                [{"location": {"x": 145.0, "y": 105.0}},
                 {"location": {"x": 155.0, "y": 115.0}}],
                [{"location": {"x": 165.0, "y": 125.0}}],
            ]},
        ]},
        "wallSegments.json": {"wallSegments": [{"id": "ws1", "wallPoints": ["wp1", "wp2"]}]},
        "wallTypes.json": {"wallTypes": [{"id": "wt1", "name": "Drywall"}]},
        "simulatedRadios.json": {"simulatedRadios": [{"accessPointId": "ap1", "transmitPower": 0.0}]},
    }
    if extra_members:
        members.update(extra_members)

    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, doc in members.items():
            z.writestr(name, json.dumps(doc, indent=1))
        for ident, blob in images.items():
            z.writestr("image-" + ident, blob)
    return path


def read_json(path: Path, name: str):
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read(name).decode("utf-8"))


@unittest.skipUnless(HAVE_PILLOW, "Pillow is not installed")
class EsxTrimmerTests(unittest.TestCase):
    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.src = make_project(self.tmp / "in.esx")
        self.out = self.tmp / "out.esx"

    # ---------------------------------------------------------------- basics
    def test_analyze_reports_without_writing_anything(self):
        report = trimmer.analyze(self.src)
        self.assertEqual(report.trimmed_count, 2)
        self.assertFalse(report.written)
        self.assertFalse(self.out.exists())
        # the source is untouched
        self.assertEqual(read_json(self.src, "floorPlans.json")["floorPlans"][0]["width"], 400.0)

    def test_every_coordinate_shifts_by_the_same_offset(self):
        before = read_json(self.src, "accessPoints.json")
        trimmer.trim(self.src, self.out)
        after = read_json(self.out, "accessPoints.json")
        plan = read_json(self.out, "floorPlans.json")["floorPlans"][0]

        a = before["accessPoints"][0]["location"]["coord"]
        b = after["accessPoints"][0]["location"]["coord"]
        dx, dy = a["x"] - b["x"], a["y"] - b["y"]
        self.assertGreater(dx, 0)
        self.assertGreater(dy, 0)

        wp_before = read_json(self.src, "wallPoints.json")["wallPoints"]
        wp_after = read_json(self.out, "wallPoints.json")["wallPoints"]
        for old, new in zip(wp_before, wp_after):
            self.assertAlmostEqual(old["location"]["coord"]["x"] - new["location"]["coord"]["x"], dx)
            self.assertAlmostEqual(old["location"]["coord"]["y"] - new["location"]["coord"]["y"], dy)

        # and nothing ends up off the cropped image
        self.assertGreaterEqual(b["x"], 0)
        self.assertLessEqual(b["x"], plan["width"])

    def test_reference_point_projections_offset_per_floor(self):
        before = read_json(self.src, "referencePoints.json")["referencePoints"][0]["projections"]
        trimmer.trim(self.src, self.out)
        after = read_json(self.out, "referencePoints.json")["referencePoints"][0]["projections"]
        plans = {p["id"]: p for p in read_json(self.out, "floorPlans.json")["floorPlans"]}
        self.assertEqual(len(after), 2)
        for old, new in zip(before, after):
            self.assertEqual(old["floorPlanId"], new["floorPlanId"])
            self.assertLess(new["coord"]["x"], old["coord"]["x"])
            plan = plans[new["floorPlanId"]]
            self.assertGreaterEqual(new["coord"]["x"], 0)
            self.assertLessEqual(new["coord"]["x"], plan["width"])

    def test_survey_route_points_are_offset_through_the_list_of_lists(self):
        name = "survey-00000000-0000-4000-8000-000000000009.json"
        before = read_json(self.src, name)["surveys"][0]["routePoints"]
        trimmer.trim(self.src, self.out)
        after = read_json(self.out, name)["surveys"][0]["routePoints"]
        self.assertEqual([len(leg) for leg in before], [len(leg) for leg in after])
        flat_before = [p["location"] for leg in before for p in leg]
        flat_after = [p["location"] for leg in after for p in leg]
        deltas = {(round(a["x"] - b["x"], 6), round(a["y"] - b["y"], 6))
                  for a, b in zip(flat_before, flat_after)}
        self.assertEqual(len(deltas), 1, f"offset should be uniform, saw {deltas}")
        self.assertNotEqual(deltas.pop(), (0.0, 0.0))

    def test_area_polygons_are_offset(self):
        before = read_json(self.src, "areas.json")["areas"][0]["area"]
        trimmer.trim(self.src, self.out)
        after = read_json(self.out, "areas.json")["areas"][0]["area"]
        self.assertEqual(len(before), len(after))
        deltas = {(round(a["x"] - b["x"], 6), round(a["y"] - b["y"], 6))
                  for a, b in zip(before, after)}
        self.assertEqual(len(deltas), 1)

    # ------------------------------------------------------------ invariants
    def test_scale_and_protected_members_are_byte_identical(self):
        trimmer.trim(self.src, self.out)
        with zipfile.ZipFile(self.src) as za, zipfile.ZipFile(self.out) as zb:
            for name in ("wallSegments.json", "wallTypes.json", "simulatedRadios.json"):
                with self.subTest(member=name):
                    self.assertEqual(za.read(name), zb.read(name))
        before = {p["id"]: p["metersPerUnit"] for p in read_json(self.src, "floorPlans.json")["floorPlans"]}
        after = {p["id"]: p["metersPerUnit"] for p in read_json(self.out, "floorPlans.json")["floorPlans"]}
        self.assertEqual(repr(before), repr(after))

    def test_declared_size_matches_the_cropped_image(self):
        trimmer.trim(self.src, self.out)
        with zipfile.ZipFile(self.out) as z:
            for plan in read_json(self.out, "floorPlans.json")["floorPlans"]:
                blob = z.read("image-" + plan["imageId"])
                w, h = Image.open(io.BytesIO(blob)).size
                self.assertEqual((float(w), float(h)), (plan["width"], plan["height"]))
                self.assertLess(w, 400)

    def test_member_set_is_preserved(self):
        trimmer.trim(self.src, self.out)
        with zipfile.ZipFile(self.src) as za, zipfile.ZipFile(self.out) as zb:
            self.assertEqual(set(za.namelist()), set(zb.namelist()))

    def test_existing_crop_rect_is_rebased_into_the_new_image(self):
        plans = [_plan(FLOOR_A, IMG_A, 400, 300, SCALE_A,
                       cropMinX=110.0, cropMinY=70.0, cropMaxX=270.0, cropMaxY=220.0)]
        src = make_project(self.tmp / "crop.esx", plans=plans, images={IMG_A: _drawing()})
        out = self.tmp / "crop-out.esx"
        trimmer.trim(src, out)
        plan = read_json(out, "floorPlans.json")["floorPlans"][0]
        self.assertGreaterEqual(plan["cropMinX"], 0.0)
        self.assertGreaterEqual(plan["cropMinY"], 0.0)
        self.assertLessEqual(plan["cropMaxX"], plan["width"])
        self.assertLessEqual(plan["cropMaxY"], plan["height"])
        self.assertLess(plan["cropMinX"], 110.0)

    def test_content_outside_the_crop_rect_is_still_kept(self):
        # A crop rect tighter than the drawing must not clip the drawing away.
        plans = [_plan(FLOOR_A, IMG_A, 400, 300, SCALE_A,
                       cropMinX=150.0, cropMinY=100.0, cropMaxX=200.0, cropMaxY=140.0)]
        src = make_project(self.tmp / "tight.esx", plans=plans, images={IMG_A: _drawing()})
        out = self.tmp / "tight-out.esx"
        trimmer.trim(src, out)
        plan = read_json(out, "floorPlans.json")["floorPlans"][0]
        # the drawn box is 140x130 plus margins, so the kept image must exceed
        # the 50x40 crop rect
        self.assertGreater(plan["width"], 120)
        self.assertGreater(plan["height"], 110)

    # -------------------------------------------------------------- refusals
    def test_svg_floor_plan_is_refused(self):
        svg = b'<?xml version="1.0"?><svg xmlns="http://www.w3.org/2000/svg"/>'
        src = make_project(self.tmp / "svg.esx",
                           plans=[_plan(FLOOR_A, IMG_A, 400, 300, SCALE_A)],
                           images={IMG_A: svg})
        report = trimmer.trim(src, self.tmp / "svg-out.esx")
        self.assertEqual(report.floors[0].action, "refused")
        self.assertIn("SVG", report.floors[0].reason)

    def test_bitmap_image_id_is_refused(self):
        src = make_project(self.tmp / "bmp.esx",
                           plans=[_plan(FLOOR_A, IMG_A, 400, 300, SCALE_A, bitmapImageId=IMG_B)],
                           images={IMG_A: _drawing(), IMG_B: _drawing(800, 600)})
        report = trimmer.trim(src, self.tmp / "bmp-out.esx")
        self.assertEqual(report.floors[0].action, "refused")
        self.assertIn("bitmapImageId", report.floors[0].reason)

    def test_gps_anchored_floor_plan_is_refused(self):
        src = make_project(self.tmp / "gps.esx",
                           plans=[_plan(FLOOR_A, IMG_A, 400, 300, SCALE_A,
                                        gpsReferencePoints=[{"lat": 1.0, "lon": 2.0}])],
                           images={IMG_A: _drawing()})
        report = trimmer.trim(src, self.tmp / "gps-out.esx")
        self.assertEqual(report.floors[0].action, "refused")
        self.assertIn("geo-anchored", report.floors[0].reason)

    def test_declared_size_disagreeing_with_the_image_is_refused(self):
        src = make_project(self.tmp / "mismatch.esx",
                           plans=[_plan(FLOOR_A, IMG_A, 999, 555, SCALE_A)],
                           images={IMG_A: _drawing()})
        report = trimmer.trim(src, self.tmp / "mismatch-out.esx")
        self.assertEqual(report.floors[0].action, "refused")
        self.assertIn("but the image is", report.floors[0].reason)

    def test_blank_floor_plan_is_skipped_not_cropped_to_nothing(self):
        blank = io.BytesIO()
        Image.new("RGB", (400, 300), "white").save(blank, format="PNG")
        src = make_project(self.tmp / "blank.esx",
                           plans=[_plan(FLOOR_A, IMG_A, 400, 300, SCALE_A)],
                           images={IMG_A: blank.getvalue()})
        report = trimmer.trim(src, self.tmp / "blank-out.esx")
        self.assertEqual(report.floors[0].action, "skipped")
        plan = read_json(self.tmp / "blank-out.esx", "floorPlans.json")["floorPlans"][0]
        self.assertEqual((plan["width"], plan["height"]), (400.0, 300.0))

    def test_already_tight_floor_plan_is_skipped(self):
        src = make_project(self.tmp / "tight2.esx",
                           plans=[_plan(FLOOR_A, IMG_A, 400, 300, SCALE_A)],
                           images={IMG_A: _drawing(400, 300, (2, 2, 398, 298))})
        report = trimmer.trim(src, self.tmp / "tight2-out.esx")
        self.assertEqual(report.floors[0].action, "skipped")
        self.assertIn("already fills", report.floors[0].reason)

    def test_missing_floor_plans_json_is_an_error(self):
        path = self.tmp / "bare.esx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("project.json", json.dumps({"project": {"id": "x"}}))
        with self.assertRaises(trimmer.TrimError):
            trimmer.analyze(path)

    def test_missing_file_is_an_error(self):
        with self.assertRaises(trimmer.TrimError):
            trimmer.analyze(self.tmp / "nope.esx")

    # ---------------------------------------------------------------- format
    def test_jpeg_floor_plan_stays_jpeg(self):
        src = make_project(self.tmp / "jpg.esx",
                           plans=[_plan(FLOOR_A, IMG_A, 400, 300, SCALE_A)],
                           images={IMG_A: _drawing(fmt="JPEG")})
        out = self.tmp / "jpg-out.esx"
        report = trimmer.trim(src, out)
        self.assertEqual(report.floors[0].action, "trimmed")
        with zipfile.ZipFile(out) as z:
            blob = z.read("image-" + IMG_A)
        self.assertEqual(trimmer.image_kind(blob), "JPEG")

    def test_image_kind_reads_magic_bytes(self):
        self.assertEqual(trimmer.image_kind(_drawing()), "PNG")
        self.assertEqual(trimmer.image_kind(_drawing(fmt="JPEG")), "JPEG")
        self.assertEqual(trimmer.image_kind(b"   <svg xmlns='x'/>"), "SVG")
        self.assertEqual(trimmer.image_kind(b"\x00\x01\x02\x03"), "UNKNOWN")

    def test_in_place_replaces_the_original(self):
        size_before = self.src.stat().st_size
        report = trimmer.trim(self.src, in_place=True)
        self.assertTrue(report.written)
        self.assertTrue(self.src.exists())
        self.assertFalse(Path(str(self.src) + ".tmp").exists())
        plan = read_json(self.src, "floorPlans.json")["floorPlans"][0]
        self.assertLess(plan["width"], 400.0)
        self.assertGreater(size_before, 0)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
