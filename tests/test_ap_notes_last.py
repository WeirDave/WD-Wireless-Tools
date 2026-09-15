"""The AP notes pages print last, in every report that can carry them.

Found by printing a project with a note on all 44 access points and reading the
PDF: 13 sheets, three of them notes pages, and the **last** sheet was the
compass reference. Six renderers put the notes at the end; the AP Placement Map
assembled them into the floor sections and then appended the compass page after
the lot.

Why the order is a decision and not a preference, in his words: the notes
section is unbounded. It is short text tables today, but an installer app that
requires a photo of every AP - Mist's does - would produce one note and one
image per access point, and an open-ended section cannot be allowed to push
fixed reference material around. Anything placed after it moves depending on how
many photos a survey happened to carry.

This reads the assembled return expression of each renderer rather than the
rendered output, because the fault was in the assembly and a rendered check
needs a project with notes on every floor to see it at all.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPORT_JS = ROOT / "web" / "assets" / "js" / "report.js"

# Things that legitimately follow the notes: a footer block and the sign-off
# block, neither of which is a reference page and neither of which an installer
# looks up by position.
ALLOWED_AFTER = {"REPORT_FOOTER", "signoff", "foot"}

# Anything in this set placed after the notes is the fault above.
PAGE_PRODUCING = {"compassPage", "toc", "sections", "maps", "overlays",
                  "legend", "matrix", "audit", "summary", "table",
                  "tableSection", "perFloorSection"}


def return_expressions(src: str) -> list[str]:
    """Every `return head + …;` that mentions the notes pages."""
    out = []
    for m in re.finditer(r"return\s+head\s*\+[^;]*;", src):
        expr = m.group(0)
        if "apNotesPages" in expr:
            out.append(expr)
    return out


class NotesGoLast(unittest.TestCase):
    def setUp(self):
        self.src = REPORT_JS.read_text(encoding="utf-8")
        self.exprs = return_expressions(self.src)

    def test_the_renderers_were_found_at_all(self):
        """A rename that made this test vacuous would otherwise pass silently."""
        self.assertGreaterEqual(len(self.exprs), 7, self.exprs)

    def test_the_notes_are_never_folded_into_an_earlier_block(self):
        """This is the shape the fault actually had, and the reason the rest of
        this file could not see it.

        The AP Placement Map did `sections += apNotesPages(...)` two dozen lines
        before its `return`, so by the time the compass page was appended there
        was nothing left to notice: the return expression did not mention the
        notes at all. Every renderer therefore concatenates them in the return,
        where what follows them is visible.
        """
        offenders = re.findall(r"^\s*\w+\s*\+=\s*apNotesPages.*$",
                               self.src, re.M)
        self.assertEqual(
            [o.strip() for o in offenders], [],
            "the notes must be concatenated in the return expression, not "
            "folded into a block something else is appended after")

    def test_nothing_that_makes_a_page_follows_the_notes(self):
        for expr in self.exprs:
            tail = expr[expr.index("apNotesPages"):]
            # Drop the call's own arguments before looking at what follows.
            tail = tail[tail.index(")") + 1:]
            names = set(re.findall(r"[A-Za-z_][A-Za-z0-9_]*", tail))
            offending = (names & PAGE_PRODUCING) - ALLOWED_AFTER
            with self.subTest(expr=" ".join(expr.split())[:90]):
                self.assertEqual(
                    offending, set(),
                    "printed after the AP notes pages: %s" % sorted(offending))

    def test_the_placement_map_specifically(self):
        """The one that was wrong, named so the regression is unmistakable."""
        found = [e for e in self.exprs if "compassPage" in e]
        self.assertTrue(found, "no renderer assembles a compass page any more")
        for expr in found:
            with self.subTest(expr=" ".join(expr.split())[:90]):
                self.assertLess(expr.index("compassPage"), expr.index("apNotesPages"),
                                "the compass reference page must come first")


if __name__ == "__main__":
    unittest.main()
