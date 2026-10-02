"""A placeholder area survives a drawn box: it is fitted, not cut.

When Prep runs Trim with Areas and Re-measure, the requirement area that still
covers the whole old canvas is named in ``placeholders=`` so the trimmer fits
it onto the new canvas for the areas step to replace. With a drawn box, the cut
ran first: every corner of a whole-canvas area lies outside any box, so the
placeholder was removed before ``_fit_placeholders`` could see it, and an areas
step that then refused left the floor with no requirement area at all.

Built on the synthetic one-floor project from ``test_prep_pipeline``.
"""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools import esx_trimmer  # noqa: E402
from tests.test_prep_pipeline import H, Image, W, canvas_area, make_esx, read  # noqa: E402

BOX = (100, 80, 700, 520)


@unittest.skipIf(Image is None, "Pillow is required to trim a floor plan")
class APlaceholderIsFittedUnderADrawnBox(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="wd-trim-ph-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def _trim(self, areas, placeholders):
        esx = make_esx(self.tmp / "Invented Annex.esx", areas=areas)
        out = self.tmp / "out.esx"
        report = esx_trimmer.trim(esx, out, boxes={"f1": list(BOX)},
                                  placeholders=placeholders)
        self.assertEqual(report.floors[0].action, "trimmed", report.floors[0])
        self.assertEqual(report.floors[0].source, "manual")
        return report, read(out, "areas.json")["areas"]

    def test_the_named_placeholder_is_kept_and_fills_the_new_canvas(self):
        report, areas = self._trim([canvas_area()], {"area-old"})
        ids = [a["id"] for a in areas]
        self.assertIn("area-old", ids, "the drawn box cut the placeholder away")
        area = areas[ids.index("area-old")]
        new_w, new_h = BOX[2] - BOX[0], BOX[3] - BOX[1]
        xs = sorted({p["x"] for p in area["area"]})
        ys = sorted({p["y"] for p in area["area"]})
        self.assertEqual(xs, [0, new_w])
        self.assertEqual(ys, [0, new_h])
        self.assertEqual(report.floors[0].dropped_count or 0, 0)

    def test_an_area_not_named_is_still_cut(self):
        """The exemption is the named placeholder only; the box still cuts."""
        other = canvas_area(area_id="area-other")
        report, areas = self._trim([canvas_area(), other], {"area-old"})
        ids = [a["id"] for a in areas]
        self.assertIn("area-old", ids)
        self.assertNotIn("area-other", ids)
        self.assertEqual(report.floors[0].dropped_count, 1)


if __name__ == "__main__":
    unittest.main()
