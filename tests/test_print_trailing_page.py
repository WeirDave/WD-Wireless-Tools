"""The blank sheet at the end of a printed report, in Firefox.

"I noticed on the document I'm currently creating and reports that after I get
a complete blank page not sure why" - on a live client deliverable, an AP
Placement Map, every page portrait.

The mechanism, measured rather than reasoned about. The report's sections carry
a named page (`page: placementPortrait`), which is how one document gets pages
of different orientations. The document's own boxes - the root, the body, the
canvas wrapping them - carry the unnamed one. A page name that changes forces a
break, so when the last section ends, the ancestors reclaim their page and
Firefox lays out one more sheet to hold them. Nothing lands on it. The only
mark on that sheet is the white the body paints; everything else the user sees
there is the browser's own header and footer.

Naming the root the same thing removes the change, and the sheet with it.

**Chromium never had this bug.** It produced six sheets before the fix and six
after. Every print check in this repository had been run in headless Chrome, so
a fault that only ever appeared in Firefox could not be seen - and Firefox is
what he prints from, at home and at work. That is the reason this file says
which engine each claim came from, and the reason the claim exists at all.

Measured through Firefox's own print pipeline - geckodriver's WebDriver Print
Page command, which is the same pagination the print dialog uses - on a real
two-floor, 49-AP project with the compass reference page forced on:

    all pages portrait    before: 7 sheets, the last blank    after: 6
    all pages landscape   before: 7 sheets, the last blank    after: 6
    Chromium, portrait    before: 6 sheets                    after: 6

The harness that produced those numbers is not in this file: it drives a real
browser against a running server, which is not something to ask of CI. What CI
can hold is that the rule is still here, still scoped, and still paired with
the named pages it exists to balance - because the way this regresses is
somebody tidying away a selector whose purpose is not obvious from its shape.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = ROOT / "web" / "assets" / "wd-tools.css"


class TrailingBlankPage(unittest.TestCase):
    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8")

    def test_the_root_shares_the_named_page(self):
        """The whole fix. Without it the ancestors take a sheet of their own."""
        self.assertIn("html:has(.rep-oriented) { page: placementPortrait; }", self.css)

    def test_it_is_scoped_to_documents_that_use_named_pages(self):
        """Unscoped, this pins every report to Letter and takes A4 away from
        anyone printing on it. A report with no oriented pages has to keep the
        paper the print dialog chose."""
        rule = re.search(r"^\s*(html[^\n{]*)\{\s*page: placementPortrait;\s*\}",
                         self.css, re.M)
        self.assertIsNotNone(rule, "the root rule is gone")
        selector = rule.group(1).strip()
        self.assertIn(":has(", selector,
                      "an unscoped html rule would pin every report to Letter")
        self.assertIn(".rep-oriented", selector)

    def test_it_names_the_same_page_the_sections_do(self):
        """The break happens because the name changes. A root named anything
        else is the same bug with an extra step."""
        self.assertIn(".rep-placement-page, .rep-oriented { page: placementPortrait; }",
                      self.css)

    def test_the_named_pages_it_balances_are_still_there(self):
        for rule in ("@page placementPortrait { size: Letter portrait; }",
                     "@page placementLandscape { size: Letter landscape; }"):
            with self.subTest(rule=rule):
                self.assertIn(rule, self.css)

    def test_the_reason_is_written_down_next_to_it(self):
        """A selector whose purpose is invisible from its shape gets tidied
        away. This one is three words long and holds up a whole sheet."""
        at = self.css.index("html:has(.rep-oriented)")
        preamble = self.css[max(0, at - 1600):at]
        for phrase in ("blank", "Firefox", "Chromium", ":has()"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, preamble,
                              "the note above the rule no longer explains it")


if __name__ == "__main__":
    unittest.main()
