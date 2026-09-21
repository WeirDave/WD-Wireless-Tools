"""The crop arithmetic in `esx_trimmer`, none of which any test had run.

Backlog item 12. Ten of the thirty unnamed functions were in this one module,
and it is the module that decides where a floor plan gets cut and what happens
to the objects sitting on it. The failure mode is not an exception: it is an
installer standing in a building holding a drawing with an access point missing
from it, which is a fault this repository has already shipped once.

Everything here is invented - two synthetic floor plans, eight-pixel PNGs, and
coordinates made up on the spot.

**The functions, and what each one is actually being asked:**

* `margin_px` - a distance on the label has to be that distance on the plan.
  The comment on it records a bug where every tight preset collapsed to the
  same ten pixels, so the presets are checked against each other, not just
  individually.
* `png_size` - reads the IHDR. Nothing in the tree calls it; see the class.
* `content_bounds` - finds the ink. Deliberately not a min/max over dark
  pixels, so it is checked against the speckle that defeats a min/max.
* `svg_viewport` / `crop_svg` - a vector plan is cropped by moving its window.
  The viewBox case and the no-viewBox case land in different places, and only
  one of them is what Ekahau's exporter writes.
* `companion_box` - the same region in a second image's pixels, with the two
  axes scaled independently because a rasteriser rounds.
* `stranded_objects` - what a refused crop tells someone is in the way.
* `offset_metadata` - moves coordinates to follow the crop.
* `cut_outside` - removes what the box excluded, following the id cascades so
  the file is not left with dangling references.
"""
from __future__ import annotations

import copy
import io
import unittest

from tools import esx_trimmer as T
from tools.esx_trimmer import TrimError

try:
    from PIL import Image
except ImportError:  # pragma: no cover - Pillow is in requirements.txt
    Image = None


FLOOR = "floor-ground"
OTHER = "floor-first"


def point(x, y, floor=FLOOR, **extra):
    item = {"location": {"floorPlanId": floor, "coord": {"x": x, "y": y}}}
    item.update(extra)
    return item


def area(points, floor=FLOOR, **extra):
    item = {"floorPlanId": floor,
            "area": [{"x": x, "y": y} for x, y in points]}
    item.update(extra)
    return item


def members():
    """A small project with objects both inside and outside a 100..400 box."""
    return {
        "accessPoints.json": {"accessPoints": [
            point(150, 150, id="ap-inside", name="ACME1-01-1-AP001"),
            point(900, 150, id="ap-right", name="ACME1-01-1-AP002"),
            point(200, 900, id="ap-below", name="ACME1-01-1-AP003"),
            point(150, 150, OTHER, id="ap-other-floor", name="ACME1-01-2-AP001"),
        ]},
        "wallPoints.json": {"wallPoints": [
            {"id": "wp-in", "location": {"floorPlanId": FLOOR,
                                         "coord": {"x": 120, "y": 120}}},
            {"id": "wp-out", "location": {"floorPlanId": FLOOR,
                                          "coord": {"x": 950, "y": 120}}},
        ]},
        "wallSegments.json": {"wallSegments": [
            {"id": "ws-kept", "wallPoints": ["wp-in", "wp-in"]},
            {"id": "ws-dangling", "wallPoints": ["wp-in", "wp-out"]},
        ]},
        "accessPointMeasurements.json": {"accessPointMeasurements": []},
        "areas.json": {"areas": [
            area([(110, 110), (390, 110), (390, 390)], name="Inside"),
            area([(110, 110), (900, 110), (900, 390)], name="Straddling"),
        ]},
        "interferers.json": {"interferers": []},
        "pictureNotes.json": {"pictureNotes": []},
    }


# ======================================================================
class MarginPresetsAreTheDistanceOnTheLabelTests(unittest.TestCase):
    """A margin is allowed to be small. It is not allowed to be a different
    number from the one on the control."""

    def test_no_scale_falls_back_to_the_default(self):
        for scale in (None, 0, -1):
            with self.subTest(meters_per_unit=scale):
                self.assertEqual(T.DEFAULT_MARGIN,
                                 T.margin_px("normal", scale))

    def test_an_unknown_preset_name_falls_back_rather_than_raising(self):
        self.assertEqual(T.DEFAULT_MARGIN, T.margin_px("enormous", 0.01))

    def test_a_preset_converts_metres_to_pixels_through_the_scale(self):
        # 3.048 m at 0.01 m per pixel is 304.8 px, rounded.
        self.assertEqual(305, T.margin_px("normal", 0.01))
        # The same distance on a coarser plan is fewer pixels: 30.48 -> 30.
        self.assertEqual(30, T.margin_px("normal", 0.1))

    def test_a_bare_number_is_taken_as_metres(self):
        self.assertEqual(100, T.margin_px(1.0, 0.01))

    def test_the_presets_stay_distinguishable_on_a_coarse_plan(self):
        """The bug the source comment records.

        The old floor was `max(DEFAULT_MARGIN, ...)`, so on a coarsely-scaled
        plan every preset below ten pixels became ten pixels and the tightest
        three produced an identical crop. A floor of 1 is what keeps the labels
        meaning different things.
        """
        coarse = 0.5  # half a metre per pixel
        widths = [T.margin_px(name, coarse) for name in
                  ("tight", "normal", "wide", "extra-wide", "parking-lot")]
        self.assertEqual(sorted(widths), widths, "presets are out of order")
        self.assertEqual(len(set(widths)), len(widths),
                         "two presets collapsed to the same pixel count: %r"
                         % (widths,))

    def test_a_margin_is_never_zero(self):
        """Zero would put the crop flush against the ink."""
        self.assertGreaterEqual(T.margin_px("tight", 1000.0), 1)


# ======================================================================
@unittest.skipIf(Image is None, "Pillow not installed")
class ContentBoundsFindsTheInkTests(unittest.TestCase):

    @staticmethod
    def canvas(w=200, h=160, colour=255):
        return Image.new("RGB", (w, h), (colour, colour, colour))

    def test_a_blank_canvas_has_no_bounds(self):
        self.assertIsNone(T.content_bounds(self.canvas(), margin=0))

    def test_a_drawn_rectangle_is_found(self):
        img = self.canvas()
        for x in range(60, 140):
            for y in range(40, 120):
                img.putpixel((x, y), (0, 0, 0))
        x0, y0, x1, y1 = T.content_bounds(img, margin=0)
        self.assertLessEqual(x0, 60)
        self.assertLessEqual(y0, 40)
        self.assertGreaterEqual(x1, 139)
        self.assertGreaterEqual(y1, 119)

    def test_the_margin_grows_the_box(self):
        img = self.canvas()
        for x in range(60, 140):
            for y in range(40, 120):
                img.putpixel((x, y), (0, 0, 0))
        tight = T.content_bounds(img, margin=0)
        wide = T.content_bounds(img, margin=12)
        self.assertLess(wide[0], tight[0])
        self.assertLess(wide[1], tight[1])
        self.assertGreater(wide[2], tight[2])
        self.assertGreater(wide[3], tight[3])

    def test_the_box_is_clamped_to_the_canvas(self):
        img = self.canvas()
        for x in range(2, 198):
            img.putpixel((x, 80), (0, 0, 0))
        x0, y0, x1, y1 = T.content_bounds(img, margin=500)
        self.assertEqual((0, 0), (x0, y0))
        self.assertEqual((200, 160), (x1, y1))

    def test_a_speck_in_the_corner_does_not_become_the_bounds(self):
        """The whole reason this is not a min/max over dark pixels.

        One stray pixel from JPEG ringing, and a strict min/max returns the
        entire canvas - a crop that reclaims nothing, reported as a success.
        """
        img = self.canvas()
        for x in range(120, 180):
            for y in range(100, 150):
                img.putpixel((x, y), (0, 0, 0))
        img.putpixel((1, 1), (0, 0, 0))          # the speck
        x0, y0, _x1, _y1 = T.content_bounds(img, margin=0)
        self.assertGreater(x0, 10, "a single corner pixel pulled the box out")
        self.assertGreater(y0, 10)


# ======================================================================
@unittest.skipIf(Image is None, "Pillow not installed")
class PngSizeReadsTheHeaderTests(unittest.TestCase):
    """Nothing in the tree calls this.

    That is worth stating rather than quietly testing: `png_size` has no
    caller in `tools/`, in `server.py` or in the tests, so it is either dead
    code or a helper somebody meant to use. It is covered here rather than
    deleted because it is three lines, it is correct, and deciding it is dead
    is a judgement for whoever owns the module - but a reader who finds it
    should know the audit flagged it.
    """

    def png(self, w, h):
        buf = io.BytesIO()
        Image.new("RGB", (w, h), (255, 255, 255)).save(buf, format="PNG")
        return buf.getvalue()

    def test_it_reads_the_declared_size(self):
        self.assertEqual((37, 91), T.png_size(self.png(37, 91)))

    def test_something_that_is_not_a_png_is_refused(self):
        for blob in (b"", b"GIF89a", b"\xff\xd8\xff\xe0 jpeg-ish",
                     b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"):
            with self.subTest(blob=blob[:12]):
                self.assertIsNone(T.png_size(blob))


# ======================================================================
class SvgIsCroppedByMovingItsWindowTests(unittest.TestCase):

    PLAIN = (b'<?xml version="1.0"?>\n'
             b'<svg xmlns="http://www.w3.org/2000/svg" width="800" '
             b'height="600"><rect x="1" y="1" width="10" height="10"/></svg>')
    VIEWBOXED = (b'<svg xmlns="http://www.w3.org/2000/svg" width="800" '
                 b'height="600" viewBox="0 0 1600 1200"><g/></svg>')

    def test_the_root_tag_is_read(self):
        start, end, w, h, vb = T.svg_viewport(self.PLAIN)
        self.assertEqual(800.0, w)
        self.assertEqual(600.0, h)
        self.assertIsNone(vb)
        self.assertTrue(self.PLAIN[start:end].startswith(b"<svg"))

    def test_units_are_stripped_from_the_declared_size(self):
        blob = self.PLAIN.replace(b'width="800"', b'width="800px"')
        self.assertEqual(800.0, T.svg_viewport(blob)[2])

    def test_a_viewbox_is_read_as_four_numbers(self):
        self.assertEqual((0.0, 0.0, 1600.0, 1200.0),
                         T.svg_viewport(self.VIEWBOXED)[4])

    def test_a_viewbox_that_cannot_be_read_refuses_the_whole_document(self):
        """Editing a window we cannot parse would move the drawing somewhere
        nobody asked for."""
        for bad in (b'viewBox="0 0 sixteen 1200"', b'viewBox="0 0 1600"'):
            with self.subTest(viewbox=bad):
                blob = self.VIEWBOXED.replace(b'viewBox="0 0 1600 1200"', bad)
                self.assertIsNone(T.svg_viewport(blob))

    def test_something_that_is_not_an_svg_is_refused(self):
        self.assertIsNone(T.svg_viewport(b"\x89PNG\r\n\x1a\n and then some"))

    def test_a_plain_document_crops_in_declared_pixels(self):
        out = T.crop_svg(self.PLAIN, (100, 50, 500, 350))
        _s, _e, w, h, vb = T.svg_viewport(out)
        self.assertEqual((400.0, 300.0), (w, h))
        self.assertEqual((100.0, 50.0, 400.0, 300.0), vb)

    def test_a_viewboxed_document_converts_the_box_into_user_units(self):
        """The document declares 800x600 and draws in 1600x1200 user units.

        A box given in declared pixels must be doubled before it is applied, or
        the crop lands in the wrong half of the drawing.
        """
        out = T.crop_svg(self.VIEWBOXED, (100, 50, 500, 350))
        _s, _e, w, h, vb = T.svg_viewport(out)
        self.assertEqual((400.0, 300.0), (w, h))
        self.assertEqual((200.0, 100.0, 800.0, 600.0), vb)

    def test_the_body_of_the_document_is_copied_through_untouched(self):
        out = T.crop_svg(self.PLAIN, (0, 0, 400, 300))
        self.assertIn(b'<rect x="1" y="1" width="10" height="10"/>', out)

    def test_a_box_with_no_area_is_refused(self):
        for box in ((100, 100, 100, 300), (100, 100, 300, 100),
                    (300, 100, 100, 300)):
            with self.subTest(box=box):
                with self.assertRaises(TrimError):
                    T.crop_svg(self.PLAIN, box)

    def test_a_document_with_no_root_element_is_refused(self):
        with self.assertRaises(TrimError):
            T.crop_svg(b"not markup at all", (0, 0, 10, 10))


# ======================================================================
class CompanionBoxMapsBetweenTwoRendersTests(unittest.TestCase):

    def test_the_same_box_in_a_double_sized_image(self):
        self.assertEqual((200, 100, 600, 400),
                         T.companion_box((100, 50, 300, 200),
                                         (400, 300), (800, 600)))

    def test_a_real_render_ratio_is_accepted(self):
        """Ekahau renders 792x612 to 5000x3863, and 612 x (5000/792) is 3863.6.

        The rasteriser rounded. Insisting the two ratios match would refuse
        every real file for an artefact of that rounding.
        """
        box = T.companion_box((0, 0, 792, 612), (792, 612), (5000, 3863))
        self.assertEqual((0, 0, 5000, 3863), box)

    def test_the_two_axes_really_do_scale_separately(self):
        """Sharper than the case above, and deliberately so.

        A full-canvas box on a nearly-proportional pair is the wrong probe:
        applying the width ratio to the height overshoots, the clamp pulls it
        back to the edge, and the answer comes out right for the wrong reason.
        Found by mutation - forcing ``sx = sy = tw / fw`` passed that test.

        So: a stretch that is emphatically not proportional, and a box in the
        middle of the image where nothing is clamped.
        """
        box = T.companion_box((100, 50, 300, 200), (400, 300), (800, 300))
        self.assertEqual((200, 50, 600, 200), box)
        # And the height must not have been scaled by the width's ratio.
        self.assertNotEqual(100, box[1])
        self.assertNotEqual(400, box[3])

    def test_the_result_is_clamped_to_the_companion(self):
        x0, y0, x1, y1 = T.companion_box((-50, -50, 5000, 5000),
                                         (400, 300), (800, 600))
        self.assertEqual((0, 0), (x0, y0))
        self.assertEqual((800, 600), (x1, y1))

    def test_an_image_of_unknown_size_is_refused(self):
        for from_size, to_size in (((0, 300), (800, 600)),
                                   ((400, 0), (800, 600)),
                                   ((400, 300), (0, 600)),
                                   ((400, 300), (800, 0))):
            with self.subTest(from_size=from_size, to_size=to_size):
                with self.assertRaises(TrimError):
                    T.companion_box((0, 0, 10, 10), from_size, to_size)

    def test_a_box_that_maps_to_nothing_is_refused(self):
        """Scaling 5000x3863 down to a thumbnail collapses a thin strip."""
        with self.assertRaises(TrimError):
            T.companion_box((100, 100, 101, 101), (5000, 3863), (50, 40))


# ======================================================================
class StrandedObjectsNamesWhatIsInTheWayTests(unittest.TestCase):

    BOX = (100, 100, 400, 400)

    def test_objects_inside_the_box_are_not_listed(self):
        items, total = T.stranded_objects(members(), FLOOR, self.BOX)
        names = [i["name"] for i in items]
        self.assertNotIn("ACME1-01-1-AP001", names)
        self.assertGreater(total, 0)

    def test_objects_outside_the_box_are_named_rather_than_counted(self):
        """A bare count sends somebody widening the box until the title block
        is back inside it, which is what the box was drawn to avoid."""
        items, _total = T.stranded_objects(members(), FLOOR, self.BOX)
        names = [i["name"] for i in items]
        self.assertIn("ACME1-01-1-AP002", names)
        self.assertIn("ACME1-01-1-AP003", names)

    def test_each_item_says_what_it_is_and_where(self):
        items, _total = T.stranded_objects(members(), FLOOR, self.BOX)
        outside = next(i for i in items if i["name"] == "ACME1-01-1-AP002")
        self.assertEqual(900.0, outside["x"])
        self.assertEqual(150.0, outside["y"])
        self.assertTrue(outside["kind"])

    def test_another_floor_is_not_this_floor_s_problem(self):
        items, _total = T.stranded_objects(members(), FLOOR, self.BOX)
        self.assertNotIn("ACME1-01-2-AP001", [i["name"] for i in items])

    def test_an_object_with_many_coordinates_is_listed_once(self):
        """An area contributes a coordinate per corner. Listing each would bury
        the access points under one polygon."""
        items, total = T.stranded_objects(members(), FLOOR, self.BOX)
        straddling = [i for i in items if i["name"] == "Straddling"]
        self.assertEqual(1, len(straddling))
        self.assertGreater(total, len(items),
                           "the total should count coordinates, the list "
                           "should not")

    def test_the_list_is_capped_but_the_total_is_not(self):
        big = {"accessPoints.json": {"accessPoints": [
            point(5000 + i, 5000, id="ap-%d" % i, name="AP%03d" % i)
            for i in range(T.MAX_STRANDED_LISTED + 25)]}}
        items, total = T.stranded_objects(big, FLOOR, self.BOX)
        self.assertEqual(T.MAX_STRANDED_LISTED, len(items))
        self.assertEqual(T.MAX_STRANDED_LISTED + 25, total)

    def test_a_box_containing_everything_strands_nothing(self):
        items, total = T.stranded_objects(members(), FLOOR,
                                          (0, 0, 10000, 10000))
        self.assertEqual(([], 0), (items, total))


# ======================================================================
class OffsetMetadataMovesTheCoordinatesTests(unittest.TestCase):

    def test_every_coordinate_on_the_floor_moves(self):
        m = members()
        T.offset_metadata(m, FLOOR, 100, 50)
        ap = m["accessPoints.json"]["accessPoints"][0]
        self.assertEqual({"x": 50, "y": 100}, ap["location"]["coord"])

    def test_another_floor_does_not_move(self):
        m = members()
        T.offset_metadata(m, FLOOR, 100, 50)
        other = next(a for a in m["accessPoints.json"]["accessPoints"]
                     if a["id"] == "ap-other-floor")
        self.assertEqual({"x": 150, "y": 150}, other["location"]["coord"])

    def test_area_corners_move_too(self):
        m = members()
        T.offset_metadata(m, FLOOR, 100, 50)
        first = m["areas.json"]["areas"][0]["area"][0]
        self.assertEqual({"x": 10, "y": 60}, first)

    def test_clamping_pulls_a_coordinate_to_the_edge_rather_than_negative(self):
        """Without it, an object just outside the crop ends up at a negative
        coordinate, which is off the canvas rather than at its edge."""
        m = members()
        T.offset_metadata(m, FLOOR, 500, 500, clamp=(400, 400))
        for ap in m["accessPoints.json"]["accessPoints"]:
            if ap["location"]["floorPlanId"] != FLOOR:
                continue
            with self.subTest(ap=ap.get("id")):
                self.assertGreaterEqual(ap["location"]["coord"]["x"], 0)
                self.assertGreaterEqual(ap["location"]["coord"]["y"], 0)
                self.assertLessEqual(ap["location"]["coord"]["x"], 400)
                self.assertLessEqual(ap["location"]["coord"]["y"], 400)

    def test_it_reports_what_it_moved_per_file(self):
        counts = T.offset_metadata(members(), FLOOR, 10, 10)
        self.assertGreaterEqual(counts.get("accessPoints.json", 0), 3)
        self.assertNotIn("interferers.json", counts,
                         "a file with nothing to move should not be reported")


# ======================================================================
class CutOutsideRemovesWhatTheBoxExcludedTests(unittest.TestCase):

    BOX = (100, 100, 400, 400)

    def test_an_object_inside_the_box_survives(self):
        m = members()
        T.cut_outside(m, FLOOR, self.BOX)
        ids = [a.get("id") for a in m["accessPoints.json"]["accessPoints"]]
        self.assertIn("ap-inside", ids)

    def test_an_object_outside_the_box_is_gone(self):
        """A drawn box is a pair of scissors. Keeping the access points from
        the rest of the building would be the surprising behaviour."""
        m = members()
        removed = T.cut_outside(m, FLOOR, self.BOX)
        ids = [a.get("id") for a in m["accessPoints.json"]["accessPoints"]]
        self.assertNotIn("ap-right", ids)
        self.assertNotIn("ap-below", ids)
        self.assertGreater(removed, 0)

    def test_another_floor_is_untouched(self):
        m = members()
        T.cut_outside(m, FLOOR, self.BOX)
        ids = [a.get("id") for a in m["accessPoints.json"]["accessPoints"]]
        self.assertIn("ap-other-floor", ids)

    def test_a_partly_outside_area_is_removed_whole(self):
        """Half an attenuation area is a worse claim than none."""
        m = members()
        T.cut_outside(m, FLOOR, self.BOX)
        names = [a.get("name") for a in m["areas.json"]["areas"]]
        self.assertIn("Inside", names)
        self.assertNotIn("Straddling", names)

    def test_a_wall_segment_pointing_at_a_removed_point_goes_with_it(self):
        """The cascade the docstring calls referential integrity.

        A dangling id is corruption the user cannot see and did not ask for.
        """
        m = members()
        T.cut_outside(m, FLOOR, self.BOX)
        seg_ids = [s["id"] for s in m["wallSegments.json"]["wallSegments"]]
        self.assertIn("ws-kept", seg_ids)
        self.assertNotIn("ws-dangling", seg_ids)

    def test_nothing_is_removed_when_the_box_holds_everything(self):
        m = members()
        before = copy.deepcopy(m)
        removed = T.cut_outside(m, FLOOR, (0, 0, 10000, 10000))
        self.assertEqual(0, removed)
        self.assertEqual(before, m)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
