"""Scale: the converter at the top, the name and full-size logo beneath it.

v2.201.0 moved the converter up by shrinking the logo to 64px beside a
one-line title. He did not want the graphic shrunk: "you shrunk down the
graphic ... if you wanted to have the entry blocks right up top that's fine
but then the scale and unit converter should be on the bottom below all
that." So the converter comes first in the page, and the title block, at its
full 180px logo, comes after the accepted formats.

Read from the page in document order and from the cascade the browser
applies (`tests/css_source.rule_for`).
"""
from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

from tests.css_source import rule_for

HTML = Path(__file__).resolve().parent.parent / "web" / "scale.html"


class _Order(HTMLParser):
    def __init__(self):
        super().__init__()
        self.seen = []

    def handle_starttag(self, tag, attrs):
        for c in (dict(attrs).get("class") or "").split():
            if c in ("scale-grid", "scale-tips", "scale-hero") and c not in self.seen:
                self.seen.append(c)


class TheConverterComesFirst(unittest.TestCase):
    def test_the_converter_then_the_formats_then_the_title(self):
        p = _Order()
        p.feed(HTML.read_text(encoding="utf-8"))
        self.assertEqual(p.seen, ["scale-grid", "scale-tips", "scale-hero"])

    def test_the_logo_is_full_size(self):
        rule = rule_for("scale.html", ".scale-hero-logo img")
        m = re.search(r"max-height\s*:\s*([0-9.]+)px", rule)
        self.assertIsNotNone(m, rule)
        self.assertGreaterEqual(float(m.group(1)), 180)


if __name__ == "__main__":
    unittest.main()
