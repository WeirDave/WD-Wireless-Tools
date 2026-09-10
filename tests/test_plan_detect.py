"""Suggesting a keep-region by comparing a CAD set's sheets to each other.

A single sheet cannot say which of its ink is drawing and which is title block;
both are ink. A set can, because the frame and title block land in the same
pixels on every sheet while the building changes. Ink that repeats is furniture;
ink that differs is plan.

The confound these tests exist for is that floors of one building genuinely do
share their outline, their core and their stairs. That shared structure reads as
"repeats on every sheet" exactly like the frame does, and a detector that simply
kept the differing ink would crop the building's own walls away. So the tests
below use sheets with a common outline *and* a common frame, and check that the
suggestion keeps the building while dropping the furniture.

Nothing here is ever applied. The suggestion carries its basis and its evidence
and the page fills the editor with it; the user confirms or drags. That is why
a slightly tight box is a acceptable outcome and a silently wrong one is not.
"""
from __future__ import annotations

import io
import json
import unittest
import zipfile
from pathlib import Path

from tools import plan_detect

try:
    from PIL import Image, ImageDraw
    HAVE_PILLOW = True
except ImportError:  # pragma: no cover
    HAVE_PILLOW = False

W, H = 1600, 1200
FRAME = (40, 40, 1560, 1160)          # drawing frame, same on every sheet
TITLE = (1330, 60, 1540, 1140)        # title block down the right edge
OUTLINE = (200, 200, 1100, 1000)      # building outline, shared by all floors


def sheet(seed: int, *, frame=True, title=True, outline=True) -> bytes:
    """One sheet of a set: shared furniture plus floor-specific partitions."""
    im = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(im)
    if frame:
        d.rectangle(list(FRAME), outline=0, width=4)
    if title:
        d.rectangle(list(TITLE), outline=0, width=3)
        for i in range(7):
            y = TITLE[1] + 70 + i * 150
            d.line([TITLE[0], y, TITLE[2], y], fill=0, width=2)
    if outline:
        d.rectangle(list(OUTLINE), outline=0, width=5)
    # Floor-specific interior partitions: different on every sheet.
    for i in range(4):
        x = OUTLINE[0] + 90 + ((seed * 67 + i * 130) % 700)
        d.line([x, OUTLINE[1] + 20, x, OUTLINE[3] - 20], fill=0, width=4)
        y = OUTLINE[1] + 70 + ((seed * 43 + i * 110) % 600)
        d.line([OUTLINE[0] + 20, y, OUTLINE[2] - 20, y], fill=0, width=4)
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    return buf.getvalue()


def floors(n, **kw):
    return [(f"floor-{i}", sheet(i, **kw), W, H) for i in range(n)]


@unittest.skipUnless(HAVE_PILLOW, "Pillow is required")
class CrossSheetTests(unittest.TestCase):
    def test_a_set_excludes_the_title_block(self):
        out = plan_detect.suggest(floors(6))
        self.assertEqual(len(out), 6)
        for s in out:
            with self.subTest(floor=s.floor_id):
                self.assertEqual(s.basis, "cross-sheet")
                self.assertLess(s.box[2], TITLE[0],
                                "the kept area must stop short of the title block")

    def test_a_set_keeps_the_building(self):
        """The shared outline is drawing, not furniture, despite repeating."""
        out = plan_detect.suggest(floors(6))
        box = out[0].box
        self.assertLessEqual(box[0], OUTLINE[0] + 60, "left edge cut into the building")
        self.assertLessEqual(box[1], OUTLINE[1] + 60, "top edge cut into the building")
        self.assertGreaterEqual(box[2], OUTLINE[2] - 60, "right edge cut into the building")
        self.assertGreaterEqual(box[3], OUTLINE[3] - 60, "bottom edge cut into the building")

    def test_every_sheet_of_a_size_gets_the_same_box(self):
        """One drag's worth of answer for the whole set."""
        out = plan_detect.suggest(floors(5))
        self.assertEqual(len({tuple(s.box) for s in out}), 1)

    def test_the_evidence_names_the_number_of_sheets(self):
        out = plan_detect.suggest(floors(14))
        self.assertEqual(out[0].sheets, 14)
        self.assertIn("14 sheets", out[0].evidence)

    def test_it_does_not_care_which_edge_the_title_block_is_on(self):
        """No rule about right edges: the same set with it along the bottom."""
        def bottom_sheet(seed):
            im = Image.open(io.BytesIO(sheet(seed, title=False)))
            d = ImageDraw.Draw(im)
            box = (60, 1010, 1540, 1150)
            d.rectangle(list(box), outline=0, width=3)
            for i in range(6):
                x = box[0] + 100 + i * 240
                d.line([x, box[1], x, box[3]], fill=0, width=2)
            buf = io.BytesIO(); im.save(buf, format="PNG")
            return buf.getvalue()

        out = plan_detect.suggest(
            [(f"f{i}", bottom_sheet(i), W, H) for i in range(6)])
        self.assertEqual(out[0].basis, "cross-sheet")
        self.assertLess(out[0].box[3], 1010,
                        "the kept area must stop short of a bottom title block")

    def test_one_marked_up_sheet_does_not_lose_the_title_block(self):
        """A revision cloud on one sheet must not make the block look variable."""
        sheets = [sheet(i) for i in range(8)]
        im = Image.open(io.BytesIO(sheets[0]))
        ImageDraw.Draw(im).ellipse([1360, 300, 1500, 420], outline=0, width=4)
        buf = io.BytesIO(); im.save(buf, format="PNG")
        sheets[0] = buf.getvalue()
        out = plan_detect.suggest([(f"f{i}", b, W, H) for i, b in enumerate(sheets)])
        self.assertLess(out[0].box[2], TITLE[0])


@unittest.skipUnless(HAVE_PILLOW, "Pillow is required")
class FallbackTests(unittest.TestCase):
    def test_a_single_floor_falls_back_and_says_so(self):
        out = plan_detect.suggest(floors(1))
        self.assertEqual(out[0].basis, "single-sheet")
        self.assertEqual(out[0].sheets, 1)
        self.assertIn("No other sheet is this size", out[0].evidence)

    def test_the_fallback_admits_it_keeps_the_title_block(self):
        """An honest claim beats a confident one."""
        out = plan_detect.suggest(floors(1))
        self.assertIn("title block is kept", out[0].evidence)

    def test_mismatched_sizes_are_grouped_not_compared(self):
        small = Image.new("L", (800, 600), 255)
        ImageDraw.Draw(small).rectangle([100, 100, 700, 500], outline=0, width=4)
        buf = io.BytesIO(); small.save(buf, format="PNG")
        mixed = floors(4) + [("odd", buf.getvalue(), 800, 600)]
        out = {s.floor_id: s for s in plan_detect.suggest(mixed)}
        self.assertEqual(out["floor-0"].basis, "cross-sheet")
        self.assertEqual(out["odd"].basis, "single-sheet")

    def test_identical_sheets_admit_they_prove_nothing(self):
        same = sheet(0)
        out = plan_detect.suggest([(f"f{i}", same, W, H) for i in range(4)])
        self.assertEqual(out[0].basis, "none")
        self.assertIsNone(out[0].box)
        self.assertIn("identical", out[0].evidence)

    def test_a_blank_sheet_does_not_crash(self):
        blank = Image.new("L", (400, 300), 255)
        buf = io.BytesIO(); blank.save(buf, format="PNG")
        out = plan_detect.suggest([("b", buf.getvalue(), 400, 300)])
        self.assertEqual(out[0].basis, "none")


@unittest.skipUnless(HAVE_PILLOW, "Pillow is required")
class SuggestionShapeTests(unittest.TestCase):
    def test_a_suggestion_is_json_serialisable(self):
        out = plan_detect.suggest(floors(3))
        json.dumps([s.as_dict() for s in out])
        d = out[0].as_dict()
        self.assertEqual(set(d), {"floorId", "box", "basis", "evidence", "sheets"})

    def test_a_box_stays_inside_the_sheet(self):
        for s in plan_detect.suggest(floors(4)):
            self.assertGreaterEqual(s.box[0], 0)
            self.assertGreaterEqual(s.box[1], 0)
            self.assertLessEqual(s.box[2], W)
            self.assertLessEqual(s.box[3], H)


@unittest.skipUnless(HAVE_PILLOW, "Pillow is required")
class EndpointTests(unittest.TestCase):
    """Through the real route, on a real archive."""

    def setUp(self):
        import tempfile
        from server import app, API_REQUEST_HEADER
        app.config.update(TESTING=True)
        self.client = app.test_client()
        self.header = API_REQUEST_HEADER
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _esx(self, n):
        plans, images, members = [], [], {}
        for i in range(n):
            fid, iid = f"floor-{i}", f"img-{i}"
            plans.append({"name": f"Level {i}", "width": float(W), "height": float(H),
                          "metersPerUnit": 0.05, "imageId": iid,
                          "gpsReferencePoints": [], "cropMinX": 0.0, "cropMinY": 0.0,
                          "cropMaxX": float(W), "cropMaxY": float(H), "id": fid})
            images.append({"imageFormat": "PNG", "resolutionWidth": float(W),
                           "resolutionHeight": float(H), "id": iid})
            members["image-" + iid] = sheet(i)
        path = Path(self.tmp.name) / "set.esx"
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("version", "1.0")
            z.writestr("project.json", json.dumps({"project": {"id": "p1"}}))
            z.writestr("floorPlans.json", json.dumps({"floorPlans": plans}))
            z.writestr("images.json", json.dumps({"images": images}))
            for k, v in members.items():
                z.writestr(k, v)
        return path.read_bytes()

    def test_the_route_returns_one_suggestion_per_floor(self):
        r = self.client.post("/api/plantrim/suggest?name=set.esx", data=self._esx(5),
                             headers={self.header: "1",
                                      "Content-Type": "application/octet-stream"})
        body = r.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(len(body["suggestions"]), 5)
        for s in body["suggestions"]:
            self.assertEqual(s["basis"], "cross-sheet")
            self.assertLess(s["box"][2], TITLE[0])
            self.assertTrue(s["evidence"])

    def test_a_project_with_no_plans_is_not_an_error(self):
        path = Path(self.tmp.name) / "empty.esx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("floorPlans.json", json.dumps({"floorPlans": []}))
        r = self.client.post("/api/plantrim/suggest?name=e.esx",
                             data=path.read_bytes(),
                             headers={self.header: "1",
                                      "Content-Type": "application/octet-stream"})
        self.assertTrue(r.get_json()["ok"])
        self.assertEqual(r.get_json()["suggestions"], [])

    def test_a_non_project_is_reported(self):
        path = Path(self.tmp.name) / "bogus.esx"
        with zipfile.ZipFile(path, "w") as z:
            z.writestr("version", "1.0")
        r = self.client.post("/api/plantrim/suggest?name=b.esx",
                             data=path.read_bytes(),
                             headers={self.header: "1",
                                      "Content-Type": "application/octet-stream"})
        self.assertFalse(r.get_json()["ok"])


class SuggestOnlyPostureTests(unittest.TestCase):
    """It fills the editor and states its case; it never acts on its own."""

    ROOT = Path(__file__).resolve().parent.parent

    def test_the_control_and_the_evidence_panel_exist(self):
        html = (self.ROOT / "web" / "plantrim.html").read_text(encoding="utf-8")
        self.assertIn('id="ptbSuggest"', html)
        self.assertIn('id="ptbEvidence"', html)

    def test_a_suggestion_fills_the_box_rather_than_trimming(self):
        js = (self.ROOT / "web" / "assets" / "js" / "plantrim.js").read_text(encoding="utf-8")
        # It writes into the same boxes a drag would, so the rectangle is on
        # screen and draggable before anything is written.
        self.assertIn("box.boxes[s.floorId] = s.box.slice()", js)
        # And it does not reach for the trim path.
        suggest = js[js.index("window.ptbSuggest"):js.index("function showEvidence")]
        self.assertNotIn("ptTrim", suggest)

    def test_the_evidence_is_shown_to_the_user(self):
        js = (self.ROOT / "web" / "assets" / "js" / "plantrim.js").read_text(encoding="utf-8")
        self.assertIn("s.evidence", js)
        self.assertIn("nothing is written until you save", js)

    def test_a_drag_supersedes_the_proposal(self):
        js = (self.ROOT / "web" / "assets" / "js" / "plantrim.js").read_text(encoding="utf-8")
        self.assertIn("delete box.suggestions[box.current]", js)

    def test_the_basis_is_always_carried(self):
        """"identical on 12 of 14" and "this is where the ink is" differ."""
        for s in plan_detect.suggest(floors(3)):
            self.assertIn(s.basis, ("cross-sheet", "single-sheet", "none"))
            self.assertTrue(s.evidence)


if __name__ == "__main__":
    unittest.main()
