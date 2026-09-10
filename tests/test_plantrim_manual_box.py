"""A drawn keep-region overrides automatic content detection.

Automatic detection reads a drawing frame and a title block as content, because
they *are* content — ink on the sheet. That is why a bare floor plate trims and
a titled CAD sheet does not, which reads as the tool being inconsistent when it
is being literal. A drawn box says what to keep and is taken at its word.

Taken at its word means genuinely so: the box is not unioned back out to the
detected content, nor to Ekahau's own display rectangle. Both of those include
the frame and the title block, so widening to them would quietly undo the drag.

The one thing a box may not do is strand an object. A box that leaves an access
point outside the kept region would put it at a negative coordinate, off the
plan, so that floor is refused with a count rather than written and explained
afterwards. Everything else about the trimmer's posture is unchanged, and the
last test here holds `metersPerUnit` to that.
"""
from __future__ import annotations

import io
import json
import unittest
import zipfile
from pathlib import Path

from tools import esx_trimmer

try:
    from PIL import Image, ImageDraw
    HAVE_PILLOW = True
except ImportError:  # pragma: no cover - environment dependent
    HAVE_PILLOW = False

FLOOR = "11111111-1111-4111-8111-111111111111"
IMAGE = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
MPU = 0.07886410844746376

# A CAD sheet: the building on the left, a title block strip down the right
# edge. Automatic detection keeps both; a drawn box keeps only the building.
SHEET_W, SHEET_H = 2000, 1500
PLAN_BOX = (200, 200, 900, 1100)
TITLE_BLOCK = (1750, 100, 1960, 1400)


def _sheet() -> bytes:
    im = Image.new("RGB", (SHEET_W, SHEET_H), (255, 255, 255))
    d = ImageDraw.Draw(im)
    d.rectangle(list(PLAN_BOX), outline=(0, 0, 0), width=5)
    d.line([PLAN_BOX[0], PLAN_BOX[1], PLAN_BOX[2], PLAN_BOX[3]], fill=(0, 0, 0), width=3)
    # Title block: a boxed strip with ruled lines, like a real one.
    d.rectangle(list(TITLE_BLOCK), outline=(0, 0, 0), width=4)
    for i in range(6):
        y = TITLE_BLOCK[1] + 60 + i * 200
        d.line([TITLE_BLOCK[0], y, TITLE_BLOCK[2], y], fill=(0, 0, 0), width=3)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def build(path: Path, *, aps=((400.0, 400.0),)) -> Path:
    members = {
        "floorPlans.json": {"floorPlans": [{
            "name": "Level 1", "width": float(SHEET_W), "height": float(SHEET_H),
            "metersPerUnit": MPU, "imageId": IMAGE, "gpsReferencePoints": [],
            "cropMinX": 0.0, "cropMinY": 0.0,
            "cropMaxX": float(SHEET_W), "cropMaxY": float(SHEET_H),
            "id": FLOOR, "status": "CREATED",
        }]},
        "images.json": {"images": [{
            "imageFormat": "PNG", "resolutionWidth": float(SHEET_W),
            "resolutionHeight": float(SHEET_H), "id": IMAGE, "status": "CREATED",
        }]},
        "accessPoints.json": {"accessPoints": [
            {"name": f"AP-{i}", "id": f"ap-{i}",
             "location": {"floorPlanId": FLOOR, "coord": {"x": x, "y": y}}}
            for i, (x, y) in enumerate(aps)
        ]},
        "wallPoints.json": {"wallPoints": [
            {"id": "wp-1", "location": {"floorPlanId": FLOOR,
                                        "coord": {"x": 250.0, "y": 250.0}}},
        ]},
        "wallSegments.json": {"wallSegments": [
            {"id": "ws-1", "wallPoints": ["wp-1"], "wallTypeId": "wt-1"}]},
        "wallTypes.json": {"wallTypes": [{"id": "wt-1", "name": "Wall, Dry"}]},
    }
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("version", "1.0")
        z.writestr("project.json", json.dumps({"project": {"id": "p-1"}}))
        for name, body in members.items():
            z.writestr(name, json.dumps(body, separators=(",", ":")))
        z.writestr("image-" + IMAGE, _sheet())
    return path


def member(path: Path, name: str):
    with zipfile.ZipFile(path) as z:
        return json.loads(z.read(name))


@unittest.skipUnless(HAVE_PILLOW, "Pillow is required")
class ManualBoxTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.src = build(self.dir / "sheet.esx")
        self.addCleanup(self.tmp.cleanup)

    # -- the reported inconsistency ---------------------------------------

    def test_automatic_detection_keeps_the_title_block(self):
        """Not a bug in detection - the title block really is ink."""
        rep = esx_trimmer.analyze(self.src)
        floor = rep.floors[0]
        if floor.action != "trimmed":
            self.skipTest(f"auto path skipped this sheet: {floor.reason}")
        # Whatever it keeps reaches across to the title block on the right.
        self.assertGreater(floor.offset[0] + floor.new_size[0], TITLE_BLOCK[0],
                           "auto detection should be including the title block")

    def test_a_drawn_box_excludes_it(self):
        rep = esx_trimmer.analyze(self.src, boxes={FLOOR: [150, 150, 950, 1150]})
        floor = rep.floors[0]
        self.assertEqual(floor.action, "trimmed", floor.reason)
        self.assertEqual(floor.source, "manual")
        self.assertEqual(floor.offset, (150, 150))
        self.assertEqual(floor.new_size, (800, 1000))
        self.assertLess(floor.offset[0] + floor.new_size[0], TITLE_BLOCK[0],
                        "the drawn box must not reach the title block")

    def test_the_box_is_not_widened_back_to_the_content(self):
        """The whole point: no union with detected bounds or the crop rect."""
        rep = esx_trimmer.analyze(self.src, boxes={FLOOR: [150, 150, 950, 1150]})
        self.assertEqual(rep.floors[0].box, (150, 150, 950, 1150))

    # -- what it writes ----------------------------------------------------

    def test_the_output_image_is_the_drawn_size(self):
        out = self.dir / "out.esx"
        esx_trimmer.trim(self.src, out, boxes={FLOOR: [150, 150, 950, 1150]})
        with zipfile.ZipFile(out) as z:
            im = Image.open(io.BytesIO(z.read("image-" + IMAGE)))
        self.assertEqual(im.size, (800, 1000))
        plan = member(out, "floorPlans.json")["floorPlans"][0]
        self.assertEqual((plan["width"], plan["height"]), (800.0, 1000.0))

    def test_coordinates_move_by_the_drawn_offset(self):
        out = self.dir / "out2.esx"
        esx_trimmer.trim(self.src, out, boxes={FLOOR: [150, 150, 950, 1150]})
        ap = member(out, "accessPoints.json")["accessPoints"][0]
        self.assertEqual(ap["location"]["coord"], {"x": 400.0 - 150, "y": 400.0 - 150})
        wp = member(out, "wallPoints.json")["wallPoints"][0]
        self.assertEqual(wp["location"]["coord"], {"x": 250.0 - 150, "y": 250.0 - 150})

    def test_meters_per_unit_is_untouched(self):
        out = self.dir / "out3.esx"
        esx_trimmer.trim(self.src, out, boxes={FLOOR: [150, 150, 950, 1150]})
        plan = member(out, "floorPlans.json")["floorPlans"][0]
        self.assertEqual(plan["metersPerUnit"], MPU)
        self.assertEqual(repr(plan["metersPerUnit"]), repr(MPU))

    def test_wall_files_are_byte_identical(self):
        out = self.dir / "out4.esx"
        esx_trimmer.trim(self.src, out, boxes={FLOOR: [150, 150, 950, 1150]})
        with zipfile.ZipFile(self.src) as a, zipfile.ZipFile(out) as b:
            for name in ("wallSegments.json", "wallTypes.json"):
                self.assertEqual(a.read(name), b.read(name), name)

    # -- refusals ----------------------------------------------------------

    def test_a_box_that_strands_an_access_point_is_refused(self):
        src = build(self.dir / "far.esx", aps=((400.0, 400.0), (1800.0, 700.0)))
        rep = esx_trimmer.analyze(src, boxes={FLOOR: [150, 150, 950, 1150]})
        floor = rep.floors[0]
        self.assertEqual(floor.action, "refused")
        self.assertIn("outside the drawn area", floor.reason)
        self.assertIn("1 object", floor.reason)

    def test_the_count_of_stranded_objects_is_reported(self):
        src = build(self.dir / "far2.esx",
                    aps=((400.0, 400.0), (1800.0, 700.0), (1810.0, 720.0)))
        rep = esx_trimmer.analyze(src, boxes={FLOOR: [150, 150, 950, 1150]})
        self.assertIn("2 objects", rep.floors[0].reason)

    def test_nothing_is_written_for_a_refused_floor(self):
        src = build(self.dir / "far3.esx", aps=((400.0, 400.0), (1800.0, 700.0)))
        out = self.dir / "far3-out.esx"
        esx_trimmer.trim(src, out, boxes={FLOOR: [150, 150, 950, 1150]})
        with zipfile.ZipFile(out) as z:
            im = Image.open(io.BytesIO(z.read("image-" + IMAGE)))
        self.assertEqual(im.size, (SHEET_W, SHEET_H), "a refused floor keeps its image")
        ap = member(out, "accessPoints.json")["accessPoints"][0]
        self.assertEqual(ap["location"]["coord"], {"x": 400.0, "y": 400.0})

    def test_a_degenerate_box_is_refused(self):
        for box in ([500, 500, 503, 900], [500, 500, 900, 502]):
            with self.subTest(box=box):
                rep = esx_trimmer.analyze(self.src, boxes={FLOOR: box})
                self.assertEqual(rep.floors[0].action, "refused")
                self.assertIn("too small", rep.floors[0].reason)

    def test_a_box_covering_the_whole_sheet_is_skipped(self):
        rep = esx_trimmer.analyze(self.src, boxes={FLOOR: [0, 0, SHEET_W, SHEET_H]})
        self.assertEqual(rep.floors[0].action, "skipped")
        self.assertIn("whole canvas", rep.floors[0].reason)

    def test_a_box_is_clamped_to_the_image(self):
        """Dragging past the edge keeps the edge, it does not fail."""
        rep = esx_trimmer.analyze(self.src, boxes={FLOOR: [-500, -500, 950, 1150]})
        floor = rep.floors[0]
        self.assertEqual(floor.action, "trimmed", floor.reason)
        self.assertEqual(floor.offset, (0, 0))

    def test_a_reversed_drag_is_normalised(self):
        """Dragging up-left gives the same box as dragging down-right."""
        a = esx_trimmer.analyze(self.src, boxes={FLOOR: [950, 1150, 150, 150]}).floors[0]
        b = esx_trimmer.analyze(self.src, boxes={FLOOR: [150, 150, 950, 1150]}).floors[0]
        self.assertEqual(a.box, b.box)

    def test_a_nonsense_box_is_refused_not_crashed(self):
        rep = esx_trimmer.analyze(self.src, boxes={FLOOR: ["a", "b", "c", "d"]})
        self.assertEqual(rep.floors[0].action, "refused")

    def test_a_floor_with_no_box_still_uses_detection(self):
        """Per-floor: drawing on one floor leaves the others automatic."""
        rep = esx_trimmer.analyze(self.src, boxes={"some-other-floor": [0, 0, 10, 10]})
        self.assertEqual(rep.floors[0].source, "auto")

    def test_the_existing_refusals_still_win_over_a_box(self):
        """A box cannot talk the tool into cropping an SVG."""
        with zipfile.ZipFile(self.src) as z:
            members = {n: z.read(n) for n in z.namelist()}
        members["image-" + IMAGE] = b'<?xml version="1.0"?><svg></svg>'
        svg = self.dir / "svg.esx"
        with zipfile.ZipFile(svg, "w", zipfile.ZIP_DEFLATED) as z:
            for n, b in members.items():
                z.writestr(n, b)
        rep = esx_trimmer.analyze(svg, boxes={FLOOR: [150, 150, 950, 1150]})
        self.assertEqual(rep.floors[0].action, "refused")
        self.assertIn("SVG", rep.floors[0].reason)


if __name__ == "__main__":
    unittest.main()
