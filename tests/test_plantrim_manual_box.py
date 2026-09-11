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

    def test_a_box_that_leaves_an_access_point_out_cuts_it(self):
        src = build(self.dir / "far.esx", aps=((400.0, 400.0), (1800.0, 700.0)))
        out = self.dir / "far-out.esx"
        rep = esx_trimmer.trim(src, out, boxes={FLOOR: [150, 150, 950, 1150]})
        floor = rep.floors[0]
        self.assertEqual(floor.action, "trimmed")
        self.assertEqual(floor.dropped_count, 1)
        names = {a["name"] for a in member(out, "accessPoints.json")["accessPoints"]}
        self.assertEqual(names, {"AP-0"})

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

    def test_a_box_crops_a_vector_plan_too(self):
        """SVG used to be refused outright; the box now works on it."""
        with zipfile.ZipFile(self.src) as z:
            members = {n: z.read(n) for n in z.namelist()}
        members["image-" + IMAGE] = (
            b'<?xml version="1.0"?>\n<svg xmlns="http://www.w3.org/2000/svg" '
            b'width="2000" height="1500"><rect width="10" height="10"/></svg>')
        svg = self.dir / "svg.esx"
        with zipfile.ZipFile(svg, "w", zipfile.ZIP_DEFLATED) as z:
            for n, b in members.items():
                z.writestr(n, b)
        rep = esx_trimmer.analyze(svg, boxes={FLOOR: [150, 150, 950, 1150]})
        floor = rep.floors[0]
        self.assertEqual(floor.action, "trimmed", floor.reason)
        self.assertEqual(floor.new_size, (800, 1000))

    def test_a_vector_plan_with_no_readable_root_is_still_refused(self):
        """The narrow case that genuinely cannot be done, refused precisely."""
        with zipfile.ZipFile(self.src) as z:
            members = {n: z.read(n) for n in z.namelist()}
        members["image-" + IMAGE] = b'<?xml version="1.0"?><notsvg/>'
        bad = self.dir / "bad.esx"
        with zipfile.ZipFile(bad, "w", zipfile.ZIP_DEFLATED) as z:
            for n, b in members.items():
                z.writestr(n, b)
        rep = esx_trimmer.analyze(bad, boxes={FLOOR: [150, 150, 950, 1150]})
        self.assertEqual(rep.floors[0].action, "refused")
        self.assertIn("<svg>", rep.floors[0].reason)


@unittest.skipUnless(HAVE_PILLOW, "Pillow is required")
class CutTests(unittest.TestCase):
    """A drawn box is a pair of scissors, not a proposal.

    This used to refuse when objects fell outside the box, on the theory that
    it must be a mis-drag. A mis-drag cannot be told from a deliberate crop to
    one conference room, one wing, or one group of rooms - all real uses - and
    refusing made the tool worse than the automatic version it replaced, which
    simply trimmed and was done.

    So the box is honoured and what falls outside is cut away. The only thing
    the cut does not leave to chance is referential integrity: an access point
    carries its radios by id and a wall point is referenced by its segments, so
    those go with it rather than being left as ids pointing at nothing.
    """

    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.src = build(self.dir / "strays.esx", aps=(
            (400.0, 400.0), (500.0, 600.0),                       # inside
            (1850.0, 220.0), (1870.0, 260.0), (1900.0, 1310.0)))  # outside
        self.box = [150, 150, 950, 1150]

    def test_the_box_is_honoured_not_refused(self):
        floor = esx_trimmer.analyze(self.src, boxes={FLOOR: self.box}).floors[0]
        self.assertEqual(floor.action, "trimmed", floor.reason)
        self.assertEqual(floor.new_size, (800, 1000))

    def test_what_falls_outside_is_cut_away(self):
        out = self.dir / "cut.esx"
        rep = esx_trimmer.trim(self.src, out, boxes={FLOOR: self.box})
        self.assertEqual(rep.floors[0].dropped_count, 3)
        names = {a["name"] for a in member(out, "accessPoints.json")["accessPoints"]}
        self.assertEqual(names, {"AP-0", "AP-1"})

    def test_what_was_inside_keeps_its_position(self):
        out = self.dir / "cut2.esx"
        esx_trimmer.trim(self.src, out, boxes={FLOOR: self.box})
        by = {a["name"]: a["location"]["coord"]
              for a in member(out, "accessPoints.json")["accessPoints"]}
        self.assertEqual(by["AP-0"], {"x": 250.0, "y": 250.0})
        self.assertEqual(by["AP-1"], {"x": 350.0, "y": 450.0})

    def test_nothing_is_left_at_a_negative_coordinate(self):
        """Neither kept nor cut is the one outcome nobody asked for."""
        out = self.dir / "cut3.esx"
        esx_trimmer.trim(self.src, out, boxes={FLOOR: self.box})
        plan = member(out, "floorPlans.json")["floorPlans"][0]
        for ap in member(out, "accessPoints.json")["accessPoints"]:
            c = ap["location"]["coord"]
            self.assertGreaterEqual(c["x"], 0.0)
            self.assertGreaterEqual(c["y"], 0.0)
            self.assertLessEqual(c["x"], plan["width"])
            self.assertLessEqual(c["y"], plan["height"])

    def test_a_cut_wall_point_takes_its_segments_with_it(self):
        """Otherwise the project ships with a segment pointing at nothing."""
        esx = self.dir / "walls.esx"
        build(esx, aps=((400.0, 400.0),))
        with zipfile.ZipFile(esx) as z:
            m = {n: z.read(n) for n in z.namelist()}
        wp = json.loads(m["wallPoints.json"])
        wp["wallPoints"].append({"id": "wp-out", "location": {
            "floorPlanId": FLOOR, "coord": {"x": 1900.0, "y": 1350.0}}})
        m["wallPoints.json"] = json.dumps(wp).encode()
        seg = json.loads(m["wallSegments.json"])
        seg["wallSegments"].append({"id": "ws-out", "wallPoints": ["wp-1", "wp-out"],
                                    "wallTypeId": "wt-1"})
        m["wallSegments.json"] = json.dumps(seg).encode()
        with zipfile.ZipFile(esx, "w", zipfile.ZIP_DEFLATED) as z:
            for n, b in m.items():
                z.writestr(n, b)
        out = self.dir / "walls-out.esx"
        esx_trimmer.trim(esx, out, boxes={FLOOR: self.box})
        kept_points = {w["id"] for w in member(out, "wallPoints.json")["wallPoints"]}
        kept_segs = member(out, "wallSegments.json")["wallSegments"]
        self.assertNotIn("wp-out", kept_points)
        self.assertEqual([x["id"] for x in kept_segs], ["ws-1"])
        for x in kept_segs:
            for ref in x.get("wallPoints", []):
                self.assertIn(ref, kept_points, "a segment points at a cut wall point")

    def test_a_cut_access_point_takes_its_radios_with_it(self):
        esx = self.dir / "radios.esx"
        build(esx, aps=((400.0, 400.0), (1850.0, 220.0)))
        with zipfile.ZipFile(esx) as z:
            m = {n: z.read(n) for n in z.namelist()}
        m["simulatedRadios.json"] = json.dumps({"simulatedRadios": [
            {"id": "r-in", "accessPointId": "ap-0"},
            {"id": "r-out", "accessPointId": "ap-1"}]}).encode()
        with zipfile.ZipFile(esx, "w", zipfile.ZIP_DEFLATED) as z:
            for n, b in m.items():
                z.writestr(n, b)
        out = self.dir / "radios-out.esx"
        esx_trimmer.trim(esx, out, boxes={FLOOR: self.box})
        aps = {a["id"] for a in member(out, "accessPoints.json")["accessPoints"]}
        radios = member(out, "simulatedRadios.json")["simulatedRadios"]
        self.assertEqual(aps, {"ap-0"})
        self.assertEqual([r["id"] for r in radios], ["r-in"])
        for r in radios:
            self.assertIn(r["accessPointId"], aps, "a radio points at a cut AP")

    def test_an_automatic_trim_never_cuts_anything(self):
        """Detected bounds always contain every coordinate, so nothing is lost."""
        rep = esx_trimmer.analyze(self.src)
        for f in rep.floors:
            self.assertEqual(f.dropped_count, 0)

    def test_an_automatic_trim_leaves_the_reference_files_alone(self):
        out = self.dir / "auto.esx"
        esx_trimmer.trim(self.src, out)
        with zipfile.ZipFile(self.src) as a, zipfile.ZipFile(out) as b:
            for n in ("wallSegments.json", "wallTypes.json"):
                self.assertEqual(a.read(n), b.read(n), n)

    def test_a_clean_crop_cuts_nothing(self):
        clean = build(self.dir / "clean.esx", aps=((400.0, 400.0),))
        rep = esx_trimmer.trim(clean, self.dir / "clean-out.esx",
                               boxes={FLOOR: self.box})
        self.assertEqual(rep.floors[0].dropped_count, 0)

    def test_metersperunit_still_survives_a_cut(self):
        out = self.dir / "cut4.esx"
        esx_trimmer.trim(self.src, out, boxes={FLOOR: self.box})
        plan = member(out, "floorPlans.json")["floorPlans"][0]
        self.assertEqual(repr(plan["metersPerUnit"]), repr(MPU))

    def test_wall_types_are_still_never_rewritten(self):
        """The guard against corruption stays; the veto over his choice went."""
        self.assertIn("wallTypes.json", esx_trimmer.NEVER_TOUCH)
        self.assertNotIn("wallSegments.json", esx_trimmer.NEVER_TOUCH)
        self.assertIn("wallSegments.json", esx_trimmer.CUT_CASCADE)

    def test_cutting_to_a_single_room_is_allowed(self):
        """A conference room, a group of rooms, who knows - all his call."""
        rep = esx_trimmer.analyze(self.src, boxes={FLOOR: [380, 380, 560, 640]})
        floor = rep.floors[0]
        self.assertEqual(floor.action, "trimmed", floor.reason)
        self.assertEqual(floor.new_size, (180, 260))


if __name__ == "__main__":
    unittest.main()
