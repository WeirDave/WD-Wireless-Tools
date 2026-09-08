"""Per-page paper orientation.

Orientation started on the placement map, keyed by floor id, because that was
the only page that could want turning. It is now a property of a page, so any
one page can differ from the rest - a wide table landscape between two upright
maps.

Two faults this guards, both of which the repository has already had:

* The pass ran only from the placement report's postRender, so no other report
  ever got its orientation applied.
* Every floor's installation table shared one key, so turning one turned them
  all - which is the opposite of what per-page means.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"
CSS = ROOT / "web" / "assets" / "wd-tools.css"


class PageOrientationTests(unittest.TestCase):
    def setUp(self):
        self.js = REPORT_JS.read_text(encoding="utf-8")
        self.css = CSS.read_text(encoding="utf-8")

    def test_the_pass_runs_for_every_report(self):
        """Not from one report's postRender, where it started."""
        start = self.js.index("window.renderReport = function ()")
        body = self.js[start:self.js.index("\n  };", start)]
        self.assertIn("applyPageOrientation(host, opts)", body,
                      "a report other than the placement map would never have "
                      "its pages turned")

    def test_page_keys_are_not_shared_between_floors(self):
        """A key without a floor in it turns every floor at once."""
        for literal in ('data-page-key="loc-table"', "'loc-table'"):
            with self.subTest(literal=literal):
                self.assertNotIn(literal, self.js,
                                 "this key is shared across floors; it needs "
                                 "the floor id appended")
        self.assertIn("'loc-table:' + ((fp && fp.id) || 'all')", self.js)

    def test_every_orientable_page_carries_a_key_and_a_kind(self):
        """The pass finds pages by data-page-key and decides by data-page-kind."""
        marked = re.findall(r'data-page-key="[^"]*"', self.js)
        self.assertGreaterEqual(len(marked), 4,
                                "the placement map, its key page, the "
                                "installation table and the compass page at "
                                "least")
        for m in re.finditer(r"data-page-key=", self.js):
            window = self.js[m.start():m.start() + 400]
            with self.subTest(at=self.js[m.start():m.start() + 60]):
                self.assertIn("data-page-kind=", window,
                              "without a kind the automatic choice cannot be "
                              "made and the page silently stays portrait")

    def test_any_page_can_turn_not_only_the_placement_map(self):
        self.assertIn(".rep-placement-page, .rep-oriented { page: placementPortrait; }",
                      self.css)
        self.assertIn(".rep-placement-page.is-landscape, .rep-oriented.is-landscape",
                      self.css)

    def test_the_table_rule_moved_with_the_table(self):
        """The installation table gained a section around it, so its page break
        belongs to the section - leaving it on the table would break inside."""
        self.assertIn(".rep-loc-page { page-break-before: always;", self.css)
        self.assertIn(".rep-loc-page .rep-loc-table { page-break-before: auto;", self.css)

    def test_a_forced_choice_is_remembered(self):
        self.assertIn("page_orient", self.js)
        self.assertIn("page_orient", (ROOT / "tools" / "settings.py").read_text(encoding="utf-8"))

    def test_a_table_is_turned_on_measured_width_not_a_column_count(self):
        """Columns are a poor proxy for how wide a table prints.

        The name page is two columns of short values and wants portrait however
        many rows it runs to. An installation table with seven columns of AP
        detail wants the long edge. A threshold on column count called the
        second one portrait, because seven is fewer than nine - the widths were
        189px and 774px against a 715px portrait sheet.
        """
        start = self.js.index("function autoOrientationFor(page)")
        body = self.js[start:self.js.index("\n  }", start)]
        self.assertIn("naturalTableWidth(table)", body)
        self.assertIn("portraitContentPx()", body)

    def test_the_printable_width_is_read_lazily(self):
        """SHEET_W_IN is declared further down the file.

        Computing the printable width at load time takes the hoisted undefined
        and gives NaN, and every comparison against NaN is false - so every
        table would have come out portrait and looked deliberate.
        """
        self.assertIn("function portraitContentPx() { return SHEET_W_IN * 96; }",
                      self.js)
        self.assertNotIn("var PORTRAIT_CONTENT_PX = SHEET_W_IN", self.js)

    def test_a_name_page_decides_for_itself(self):
        """Not inherited from the floor whose map it follows.

        Floor 1's map prints landscape and its name page prints portrait in the
        same document; keying the page separately is what allows that.
        """
        self.assertIn("'key:' + fp.id", self.js)
        self.assertIn('data-page-kind="table"', self.js)

    def test_the_older_setter_name_still_works(self):
        """Anything still calling setFloorOrient must not break."""
        self.assertIn("window.setFloorOrient = window.setPageOrient", self.js)


if __name__ == "__main__":
    unittest.main()
