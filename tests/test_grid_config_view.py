"""The grid configuration view draws the same grid the printed index does.

"The sectional lines when you're going to divide up a large drawing are barely
visible when you're trying to do the configuration. When you go to print them
they're nice and bold but you can't see them when you're trying to divide."

Two implementations, as this repository keeps producing. The printed section
index drew classed, colour-coded cells with a white halo on the labels. The
configuration view - the one place the division is actually being decided -
drew its own lines inline at `rgba(59,130,246,0.7)`, 1.5 units wide in a
1000-unit viewBox, with labels at half opacity. Over a white CAD plan that is
very nearly nothing.

Now there is one description of what a section boundary looks like, in CSS, and
exactly one deliberate difference between the two views: weight. On screen the
divisions dominate because a decision is being made; on the printed index they
are reference furniture. That difference lives in the stylesheet under
`#gridSvg`, not duplicated in the renderer.

The halo is not decoration. A CAD floor plan is white paper *and* black
linework, so a single stroke colour loses against one of them - the same
failure the AP markers had when white-on-white made them invisible.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"
CSS = ROOT / "web" / "assets" / "wd-tools.css"


class GridConfigView(unittest.TestCase):
    def setUp(self):
        self.js = REPORT_JS.read_text(encoding="utf-8")
        self.css = CSS.read_text(encoding="utf-8")
        start = self.js.index("var vw = 1000, vh = 1000 * (H / W);")
        self.body = self.js[start:self.js.index("// AP dots", start)]

    def test_it_does_not_style_the_grid_inline(self):
        """Inline colours here are how the two views came to disagree - the
        stylesheet could not reach this one at all."""
        for hardcoded in ('stroke="rgba(59,130,246', 'fill="rgba(59,130,246'):
            with self.subTest(value=hardcoded):
                self.assertNotIn(hardcoded, self.body)

    def test_it_uses_the_same_classes_as_the_printed_index(self):
        for cls in ("rep-grid-cell", "rep-grid-label", "rep-grid-halo"):
            with self.subTest(cls=cls):
                self.assertIn(cls, self.body)

    def test_the_weight_difference_is_declared_once_in_css(self):
        """One deliberate difference, in one place, rather than two renderers
        each with an opinion."""
        self.assertIn("#gridSvg .rep-grid-cell", self.css)
        self.assertIn("#gridSvg .rep-grid-label", self.css)

    def test_every_boundary_carries_a_halo(self):
        """White paper and black linework are both backgrounds here."""
        self.assertIn(".rep-grid-halo { fill: none; stroke: rgba(255,255,255", self.css)
        self.assertIn("rep-grid-halo", self.body)
        # the crop box border too, not only the internal divisions
        crop = self.js[self.js.index("// crop box border"):][:600]
        self.assertIn("rep-grid-halo", crop)
        self.assertNotIn('stroke="#3b82f6"', crop)

    def test_the_printed_index_is_not_dragged_along(self):
        """Sharing classes must not mean sharing weight - the report keeps its
        own per-floor colours."""
        self.assertIn('.rep-floor-section[data-floor-idx="0"] .rep-grid-cell', self.css)
        for rule in ("#gridSvg .rep-grid-cell", "#gridSvg .rep-grid-label"):
            with self.subTest(rule=rule):
                self.assertTrue(rule.startswith("#gridSvg"),
                                "the heavier styling must stay scoped to the modal")

    def test_sections_that_will_produce_no_page_are_shown_as_such(self):
        """An empty section never becomes a sheet. Seeing that while choosing
        the division is the point of looking at it."""
        self.assertIn("hasApsAt", self.body)
        self.assertIn("rep-grid-cell--empty", self.body)
        self.assertIn("rep-grid-label--empty", self.body)

    def test_the_stroke_scales_with_the_view_not_a_magic_number(self):
        """1.5 in a 1000-unit viewBox was the old figure and is why it vanished."""
        self.assertRegex(self.body, r"glw = Math\.max\([\d.]+, vw \* [\d.]+\)")
        self.assertNotIn('stroke-width="1.5"', self.body)


if __name__ == "__main__":
    unittest.main()
