"""The compass reference has to be one page.

It shipped as two columns - the rose in a fixed 220px column on the left, all
the prose in a flexible column on the right - and ran six lines onto a second
sheet. Two separate costs, both invisible in the source:

* the prose got about two thirds of the printable width for the whole height of
  the page, so every paragraph wrapped more than it needed to; and
* the ~5in of left column below the rose was dead space no text could reach.

Measured from real PDFs printed by headless Chrome at the shipped @page margins
(0.4in sides, 0.4in top, 0.6in bottom):

    before   portrait   2 pages   6 lines / 84pt spilled onto sheet 2
    after    portrait   1 page    662pt used of 720pt   (58pt spare)
    after    landscape  1 page    500pt used of 523pt   (23pt spare on A4)

The landscape figure is checked against A4 rather than Letter deliberately:
turned on its side A4 is the shorter sheet (7.27in of printable height against
Letter's 7.5in), and the rest of this file's sizing already takes the width from
A4 and the height from Letter so one layout is right on both.

Nothing here re-measures - that needs Chrome and PyMuPDF, which CI does not
have. What it does is hold the two structural decisions that bought the space,
so neither can be undone without a test going red and this page quietly going
back to two sheets.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "web" / "assets" / "wd-tools.css"
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"


class CompassPageLayout(unittest.TestCase):
    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8")
        self.js = REPORT_JS.read_text(encoding="utf-8")

    def _print_block(self) -> str:
        """The @media print rules for this page."""
        start = self.css.index(".rep-compass-page { page-break-before: always;")
        return self.css[start:start + 3000]

    def test_the_rose_sits_in_the_text_not_in_a_column_of_its_own(self):
        """The fix, and the thing most likely to be undone by a later tidy-up.

        A side column costs the prose its width for the full height of the page
        and strands whatever space is left under the rose. Floating it costs
        only the height of the rose itself.
        """
        start = self.css.index(".rep-compass-body {")
        body = self.css[start:self.css.index("}", start)]
        self.assertNotIn("flex", body,
                         "a flex row here is the two-column layout that ran "
                         "this page onto a second sheet")
        left_start = self.css.index(".rep-compass-left {")
        left = self.css[left_start:self.css.index("}", left_start)]
        self.assertIn("float: left", left)

    def test_the_float_is_cleared(self):
        """Without this the section box ends above the rose and the next page's
        content rides up into it."""
        self.assertIn(".rep-compass-body::after { content: ''; display: block; clear: both; }",
                      self.css)

    def test_print_does_not_reinstate_a_fixed_side_column(self):
        block = self._print_block()
        self.assertNotIn("flex:", block,
                         "the print rules used to pin the rose column to 220px")

    def test_landscape_gets_columns_rather_than_a_ten_inch_measure(self):
        """Full width on the long edge is ~150 characters a line."""
        block = self._print_block()
        self.assertIn(".rep-compass-page.is-landscape .rep-compass-body { columns: 2;", block)

    def test_landscape_sections_may_split(self):
        """Two columns of a landscape sheet is about 1080pt against roughly
        1000pt of content, so a section that refuses to split cannot be placed
        and is thrown to a second sheet - the exact fault being fixed.

        Portrait keeps the avoid: it has the room, and a heading stranded at the
        foot of a page is the same fault one scale down.
        """
        block = self._print_block()
        self.assertIn(".rep-compass-sect { break-inside: avoid; page-break-inside: avoid; }",
                      block, "portrait still keeps sections whole")
        self.assertRegex(
            block,
            r"\.rep-compass-page\.is-landscape \.rep-compass-sect \{\s*"
            r"break-inside: auto; page-break-inside: auto;",
            "landscape must let a section split across its two columns")

    def test_the_landscape_rose_is_smaller_than_the_portrait_one(self):
        """A landscape sheet is 2.7in shorter, and the rose sits at the head of
        a column where every point it takes pushes text toward a second sheet.
        At the portrait size this page cleared Letter landscape by 5pt and would
        have run over on A4."""
        m = re.search(r"\.rep-compass-page\.is-landscape \.rep-comp-rose \{ width: (\d+)px",
                      self.css)
        self.assertIsNotNone(m, "landscape needs its own rose size")
        landscape_px = int(m.group(1))
        portrait_px = int(re.search(r"\.rep-comp-rose \{ width: (\d+)px", self.css).group(1))
        self.assertLess(landscape_px, portrait_px)

    def test_the_page_can_still_be_turned_by_hand(self):
        """It is one of the pages the per-page orientation pass walks, so the
        reader can put it whichever way round suits the rest of the document -
        and both ways round have been measured to fit."""
        self.assertIn('data-page-key="compass"', self.js)
        self.assertIn("orientPickerHtml('compass', opts)", self.js)


if __name__ == "__main__":
    unittest.main()
