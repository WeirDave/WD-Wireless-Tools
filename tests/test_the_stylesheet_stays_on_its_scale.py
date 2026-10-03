"""The shared stylesheet stays on its scales, and its debt only goes down.

Step 1 of the suite-wide visual refresh ("put a fresh coat of paint on all
tools and really make them look like a production value High dollar tool").
What made the suite look hand-built was measurable: 1,092 colour literals in
`wd-tools.css`, 43 font sizes, fifteen corner radii - each rule written on its
own day with its own numbers. A refresh that fixes them once and leaves the
door open gets them back by the next release.

* **Corners are finished**: every single-value `border-radius` names a token
  (`--r-xs` 4, `--r-sm` 6, `--r-md` 8, `--r-lg` 12, `--radius-pill`) or is one
  of the hairline values kept literal on purpose.
* **Colours and font sizes are a ratchet**: the counts below are what was
  there when this was written. A change may lower them - and should lower the
  constant with it - and may never raise them. A new colour belongs in a
  token; a tool's colour belongs in the brand block.

Counted with comments stripped, so a comment explaining a colour is not one.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

CSS = Path(__file__).resolve().parent.parent / "web" / "assets" / "wd-tools.css"

#: Lower these when you remove debt. Never raise them.
MAX_COLOUR_LITERALS = 986
MAX_FONT_SIZES = 41

RADIUS_TOKENS = {"--r-xs", "--r-sm", "--r-md", "--r-lg", "--radius-pill", "--radius"}
#: Hairlines and bars, where the smallest token would make a pill; 0 is no corner.
RADIUS_LITERALS = {"0", "1px", "2px", "50%"}


def _bare() -> str:
    return re.sub(r"/\*.*?\*/", "", CSS.read_text(encoding="utf-8"), flags=re.S)


class TheStylesheetStaysOnItsScale(unittest.TestCase):
    def test_every_corner_is_on_the_scale(self):
        off = []
        for value in re.findall(r"border-radius:\s*([^;]+);", _bare()):
            value = value.replace("!important", "").strip()
            if " " in value:          # per-corner shorthand: a tab, a joined edge
                continue
            m = re.fullmatch(r"var\((--[\w-]+)\)", value)
            if m and m.group(1) in RADIUS_TOKENS:
                continue
            if value in RADIUS_LITERALS:
                continue
            off.append(value)
        self.assertEqual(off, [], "border-radius off the scale - use --r-xs/sm/md/lg")

    def test_colour_literals_do_not_grow(self):
        n = len(re.findall(r"#[0-9a-fA-F]{3,8}\b|rgba?\(|hsla?\(", _bare()))
        self.assertLessEqual(
            n, MAX_COLOUR_LITERALS,
            "new colour literals in wd-tools.css: use a token. If you removed some, "
            "lower MAX_COLOUR_LITERALS to %d." % n)

    def test_font_sizes_do_not_multiply(self):
        sizes = set(re.findall(r"font-size:\s*([0-9.]+(?:px|rem|em|pt))", _bare()))
        self.assertLessEqual(
            len(sizes), MAX_FONT_SIZES,
            "a new font size; use one already on the page. Sizes: %s" % sorted(sizes))


if __name__ == "__main__":
    unittest.main()
