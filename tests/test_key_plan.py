"""The Key Plan on every segmented section page.

Standard AEC name, deliberately. A construction reader recognises "Key Plan" on
sight and learns nothing from a label we invented - the same reason match lines
will be called match lines.

A whole-floor thumbnail with the current section shaded already existed. What it
did not do was draw the other sections, so it said which rectangle you were in
without saying what adjoined it - which is most of what someone standing in a
warehouse actually needs. Every section is now outlined and lettered, with the
current one filled.

The caption sits outside the framed thumbnail. That frame carries aspect-ratio
and overflow:hidden so the plan keeps its proportions, and anything else placed
inside is clipped away without trace: printed with the caption inside the frame,
the words do not appear in the PDF at all. Verified both ways round rather than
assumed.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"
CSS = ROOT / "web" / "assets" / "wd-tools.css"


class KeyPlan(unittest.TestCase):
    def setUp(self):
        self.js = REPORT_JS.read_text(encoding="utf-8")
        self.css = CSS.read_text(encoding="utf-8")
        start = self.js.index("function renderAntennaLocatorThumb(")
        self.body = self.js[start:self.js.index("\n  function ", start + 10)]

    def test_it_uses_the_standard_name(self):
        """Not "locator", not "mini-map". The people receiving these drawings
        read key plans every day."""
        self.assertIn(">Key Plan<", self.body)

    def test_the_caption_is_outside_the_clipped_frame(self):
        """.rep-seg-locator has aspect-ratio and overflow:hidden. A caption
        inside it is clipped and never reaches the paper - confirmed by
        printing it both ways."""
        self.assertIn("rep-seg-keyplan", self.body)
        frame = self.body[self.body.index("rep-seg-locator\" style="):]
        caption_at = frame.index("rep-seg-locator-caption")
        close_at = frame.index("+ '</div>'")
        self.assertLess(close_at, caption_at,
                        "the frame must be closed before the caption is added")

    def test_every_section_is_drawn_not_only_the_current_one(self):
        """Knowing which rectangle you are in does not tell you what is next to
        it, and following a run of racking across pages needs the second."""
        self.assertIn("rep-seg-locator-other", self.body)
        self.assertIn("cells || []", self.body)

    def test_every_section_is_lettered_with_its_own_label(self):
        self.assertIn("segCellLabel(c.col, c.row)", self.body)

    def test_the_current_section_is_distinguishable(self):
        self.assertIn("is-here", self.body)
        self.assertIn("rep-seg-locator-rect", self.body)
        self.assertIn(".rep-seg-locator-label.is-here", self.css)

    def test_the_sections_reach_the_thumbnail(self):
        """They are computed in the segmented overview and were not passed
        down; without this the key plan can only ever draw one box."""
        self.assertIn("renderAntennaSegmentCell(url, W, H, cell, opts, ctx, keyHtml, cells)",
                      self.js)
        self.assertIn("renderAntennaLocatorThumb(url, W, H, cell, opts.cropBox, cells)",
                      self.js)

    def test_lettering_is_dropped_when_it_would_not_be_readable(self):
        """A thumbnail is about 90px wide. Past a couple of dozen sections the
        letters stop being legible and become texture."""
        self.assertIn("showLabels", self.body)

    def test_it_survives_print(self):
        """Colours are set for screen; print needs its own, or the outlines and
        letters vanish into the plan behind them."""
        block = self.css[self.css.index(".rep-seg-locator-other"):]
        self.assertIn("@media print", block[:1200])
        self.assertIn(".rep-seg-locator-caption { color:", block[:1200])


if __name__ == "__main__":
    unittest.main()
