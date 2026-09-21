"""A short report is one sheet, in every engine.

Found by printing the same report in Chrome, Edge and Firefox and comparing page
counts: the Antenna Aim Sheet came out as **one page in Chromium and two in
Firefox**, the second carrying nothing but the page background.

`min-height: 100vh` is a screen rule — it means "at least the window". In paged
media `100vh` is **the sheet**, so every element carrying it was forced to a full
page of minimum height however little was on it, and the padding above it then
pushed past the bottom edge. Chromium clamps this; Firefox takes it literally,
which is why it only showed up in the browser the reports are printed from.

Two things worth keeping from how this was fixed. The first attempt reset
`html, body` and **did not work** — `.report-workspace.active` carries the same
rule and is more specific, so the sheet stayed a sheet tall. And the evidence
that settled it was in the PDF itself: both pages carried a white fill spanning
the whole printable area, which is an ancestor box two pages tall, not content
that overflowed.

So every full-height shell is listed, not just the one that was caught.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "web" / "assets" / "wd-tools.css"

# Selectors that carry a viewport height on screen and must not in print.
FULL_HEIGHT_SHELLS = [
    "body.tool-report",
    "body.tool-scale",
    ".report-workspace.active",
    ".editor.active",
    ".app",
    "#appScreen",
    "#loginScreen",
    "#setupScreen > div",
]


class PrintResetsTheFullHeightShells(unittest.TestCase):
    def setUp(self):
        self.css = CSS.read_text(encoding="utf-8")
        start = self.css.index("@media print")
        self.print_block = self.css[start:]
        reset_at = self.print_block.index("min-height: 0 !important")
        # The selector list this reset belongs to.
        head = self.print_block[:reset_at]
        self.reset_selectors = head[head.rindex("}") + 1:]

    def test_the_reset_exists_at_all(self):
        self.assertIn("min-height: 0 !important", self.print_block)
        self.assertIn("height: auto !important", self.print_block)

    def test_every_full_height_shell_is_reset(self):
        """The first fix reset only html/body and the bug survived."""
        for sel in FULL_HEIGHT_SHELLS:
            with self.subTest(selector=sel):
                self.assertIn(sel, self.reset_selectors)

    def test_body_alone_is_not_treated_as_sufficient(self):
        """Guards the exact mistake: the wrapper is the specific one."""
        self.assertIn(".report-workspace", self.reset_selectors)

    def test_the_banner_padding_goes_too(self):
        """It reserves room for banners that are display:none in print."""
        self.assertIn("padding-top: 0 !important", self.print_block)

    def test_no_new_viewport_height_escapes_the_reset(self):
        """Any element given 100vh on screen has to be listed above.

        A new full-height shell added later is exactly how this comes back, so
        the rule is checked against the stylesheet rather than remembered.
        """
        screen = self.css[:self.css.index("@media print")]
        offenders = set()
        for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", screen):
            selector, body = m.group(1), m.group(2)
            if "100vh" not in body:
                continue
            # `height` and `min-height` only. A `max-height` in viewport units
            # is an upper bound - it can shrink a box, never force one to a
            # full sheet - so it cannot cause the extra page this guards, and
            # matching it caught the menu height cap, which is a scroll fix.
            # Substring matching is what let `max-height` in: it contains
            # "height".
            if not re.search(r"(^|[;{\s])(min-)?height\s*:[^;]*100vh", body):
                continue
            for part in selector.split(","):
                part = part.strip().split("\n")[-1].strip()
                if not part or part.startswith("@") or part.startswith("."):
                    pass
                offenders.add(part)
        known = set(FULL_HEIGHT_SHELLS) | {"body", "html", ".report-workspace"}
        unlisted = {
            o for o in offenders
            if o and not any(k in o or o in k for k in known)
        }
        self.assertEqual(
            unlisted, set(),
            "these carry a viewport height on screen and are not reset in "
            "print, so a short document will print an extra sheet in Firefox: "
            "%s" % sorted(unlisted))


if __name__ == "__main__":
    unittest.main()
