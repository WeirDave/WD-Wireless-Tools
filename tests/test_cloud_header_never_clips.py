"""Nothing in Cloud Manager's header is ever cut off, at any width he uses.

"clearly they didn't test this in different resolutions. I'm on my laptop and
the buttons run over and get cut off on the menu up top. Test cloud in
different resolutions and rework the design until we have a usable working
surface at any resolution."

**Measured in Firefox before the fix**, with the selection-dependent controls
visible, which is the widest the bar ever gets:

    width      intrinsic bar   controls cut off
    1024        2342px          15
    1366        2342px          12
    1440        2342px          11
    1536        2342px          10
    1920        2342px           5
    2560        2342px           0

The bar only ever fitted on a 2560 monitor. Everywhere else the overflow ran
off the window and the page scrolled sideways - a control past the edge is not
merely ugly, it cannot be clicked.

Two containers, the same fault: `display: flex` with no `flex-wrap`, which
defaults to `nowrap`. The toolbar overflowed its window; the filter cards
shrank under `flex: 0 1 auto` and clipped their own labels, so "Mismatches"
and "Name Matches" read as fragments.

After: **0 cut off at every width**, no sideways scroll, every label intact.
The bar takes a second line at 1920 and below and a third at 1024.

These assertions are the guard rather than the verification - the verification
was the browser. A CI runner has no Firefox, so what is held here is the shape
of the fix, with the numbers above recording what was actually seen.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CSS = (ROOT / "web" / "assets" / "wd-tools.css").read_text(encoding="utf-8")


def rule(selector: str) -> str:
    """Every rule for this selector, joined.

    Taking the first match is a trap this file walked into on its first run:
    `body.tool-cloud .toolbar` is declared twice, once as a one-line
    `{ position: relative; }` hundreds of lines above the real block, and the
    first-match lookup found the decoy. A selector may be declared as often as
    it likes, so "does this selector set flex-wrap" has to consider all of them.
    """
    out = []
    for m in re.finditer(re.escape(selector) + r"\s*\{", CSS):
        start = m.start()
        out.append(CSS[start:CSS.index("}", start)])
    if not out:
        raise AssertionError("no rule found for " + selector)
    return "\n".join(out)


class TheHeaderWrapsRatherThanClippingTests(unittest.TestCase):

    def test_the_toolbar_wraps(self):
        """The whole bug in one property. Without it the bar keeps its
        intrinsic 2342px and everything past the window edge is unreachable."""
        body = rule("body.tool-cloud .toolbar")
        self.assertIn("flex-wrap: wrap", body)
        self.assertIn("row-gap", body,
                      "wrapped lines need vertical spacing or they collide")

    def test_nothing_in_the_toolbar_shrinks_below_its_label(self):
        """Wrapping alone still leaves flex free to squeeze a button until its
        own text is clipped inside it - the same failure one level down."""
        self.assertIn("body.tool-cloud .toolbar > * { flex-shrink: 0; }", CSS)

    def test_the_filter_cards_wrap(self):
        body = rule(".dashboard")
        self.assertIn("flex-wrap: wrap", body)

    def test_a_filter_card_does_not_squeeze_under_its_own_name(self):
        """`flex: 0 1 auto` let the cards compress and clip their labels. A
        counter whose name you cannot read is not a counter."""
        body = rule(".dash-card")
        self.assertIn("flex: 0 0 auto", body)
        self.assertNotIn("flex: 0 1 auto", body)


class TheLabelsStayTests(unittest.TestCase):
    """Reclaiming width by hiding the text would undo a fix he asked for.

    He could not identify the icon-only buttons, said so, and the labels went
    in because of that. Narrow is allowed to wrap, take more height, and look
    less tidy. It is not allowed to go back to icons.
    """

    def test_the_narrow_breakpoint_does_not_hide_toolbar_labels(self):
        blocks = re.findall(r"@media \(max-width: \d+px\) \{(.*?)\n\}", CSS,
                            re.S)
        self.assertTrue(blocks, "no narrow breakpoints at all?")
        for b in blocks:
            self.assertNotIn(".btn { font-size: 0", b)
            self.assertNotIn("body.tool-cloud .toolbar .btn { display: none", b)

    def test_the_icon_button_labels_are_only_dropped_on_the_row_controls(self):
        """`.ib-label` belongs to the in-row gutter arrows, which are a
        different problem with a different answer. The toolbar's own buttons
        carry plain text and keep it at every width."""
        self.assertIn(".ib-label { display: none; }", CSS)
        self.assertNotIn(".toolbar .btn span { display: none", CSS)


if __name__ == "__main__":
    unittest.main()
