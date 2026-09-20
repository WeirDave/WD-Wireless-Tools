"""An HTML attribute needs the attribute escaper, not the text one.

`WD.esc` escapes by round-tripping through `textContent`, so it converts `&`,
`<` and `>` and **leaves the double quote alone** - which is correct, because a
quote needs no escaping in element text. `WD.escAttr` escapes the quote and the
apostrophe as well. The two are not interchangeable, and the one that looks
like the general-purpose escaper is the one that is wrong inside an attribute.

**This was live.** An AP name is read straight out of the `.esx` and rendered
into the preview table as `title="' + esc(curTxt) + '"`. A project whose AP was
named

    <img src=x onerror="...">" onmouseover="..." HOSTILE

closed the `title` attribute on its own quote and everything after it parsed as
further attributes, so a real `onmouseover` handler landed on two `<td>` cells
and ran when the pointer crossed them. The *text* on either side of it was
escaped correctly the whole time, which is why reading the line did not show
it: the bug is in the quoting of the attribute, not in the escaping of the
content. Driving a hostile `.esx` through AP Labeler in Firefox is what found
it.

Twenty-five call sites across seven files had the same shape. Two other files -
`walls-swap.js` and `settings-page.js` - had already grown their own local
`esc` that escapes the quote, which is the same "three private copies of the
answer" pattern that `WD.readableOn` exists to stop; they were left correct and
switched to the shared helper.

So this file is a guard rather than a unit test: it reads the shipped JavaScript
and fails if an attribute value is ever built with the text escaper again.
"""
from __future__ import annotations

import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

JS_DIR = ROOT / "web" / "assets" / "js"

# `attr="` immediately followed by a call to a text escaper, in any of the four
# ways this codebase builds markup.
TEXT_ESCAPER_IN_ATTR = [
    re.compile(r"""(\w[\w-]*)\s*=\s*"\s*\+\s*(?:WD\.)?\b(esc|e)\s*\("""),
    re.compile(r"""(\w[\w-]*)\s*=\s*"'\s*\+\s*(?:WD\.)?\b(esc|e)\s*\("""),
    re.compile(r"""(\w[\w-]*)\s*=\s*\\?"\$\{\s*(?:WD\.)?(esc|e)\s*\("""),
    re.compile(r"""(\w[\w-]*)\s*=\s*'\s*\+\s*(?:WD\.)?\b(esc|e)\s*\("""),
]


class AttributeEscaping(unittest.TestCase):

    def test_no_attribute_is_built_with_the_text_escaper(self):
        """Every `attr="..."` interpolation uses escAttr, a(), or WD.escAttr.

        A hit here is not necessarily exploitable - the value may be a constant
        this file controls - but the shape is the one that was exploitable, and
        allowing the safe-looking cases back in is how the unsafe ones return.
        """
        offenders = []
        for path in sorted(JS_DIR.glob("*.js")):
            for lineno, line in enumerate(
                    path.read_text(encoding="utf-8", errors="replace").split("\n"), 1):
                for pattern in TEXT_ESCAPER_IN_ATTR:
                    for match in pattern.finditer(line):
                        offenders.append(
                            f"{path.name}:{lineno} attribute `{match.group(1)}` "
                            f"uses `{match.group(2)}(` - use the attribute escaper")
        self.assertEqual(
            [], offenders,
            "attribute values must use escAttr/a(), which escapes the quote:\n  "
            + "\n  ".join(offenders))

    def test_the_two_escapers_differ_on_the_quote(self):
        """The distinction this whole file rests on, asserted directly.

        If `WD.esc` ever starts escaping the quote this guard becomes
        unnecessary; it should fail loudly rather than quietly stay true.
        """
        shared = (JS_DIR / "wd-shared.js").read_text(encoding="utf-8")

        esc_body = re.search(r"WD\.esc\s*=\s*function[^}]*?\{(.*?)\n  \};",
                             shared, re.S)
        self.assertIsNotNone(esc_body, "WD.esc not found in wd-shared.js")
        self.assertIn("textContent", esc_body.group(1),
                      "WD.esc is expected to escape via textContent, which "
                      "does not touch the double quote")

        attr_body = re.search(r"WD\.escAttr\s*=\s*function[^}]*?\{(.*?)\n  \};",
                              shared, re.S)
        self.assertIsNotNone(attr_body, "WD.escAttr not found in wd-shared.js")
        for needed in ('&quot;', '&#39;', '&amp;', '&lt;', '&gt;'):
            self.assertIn(needed, attr_body.group(1),
                          f"WD.escAttr must produce {needed}")


if __name__ == "__main__":
    unittest.main()
