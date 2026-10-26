"""No page carries an attribute that is really a fragment of a broken one.

A double quote inside a double-quoted attribute ends it there. `home.html` had

    title="Replaces Ekahau's default "Simulated AP-xxx" names with ..."

so the tooltip stopped at "default ", and `AP-xxx"`, `define,` and `.esx."`
became attributes of the link. Nothing failed - the tile worked - which is why
it stayed. The check parses every shipped page the way a browser tokenises it
and fails on an attribute name no author would have written.
"""
from __future__ import annotations

import re
import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

#: What an attribute name looks like when someone meant it.
VALID_NAME = re.compile(r"^[A-Za-z_:@][\w:.-]*$")


class _Attributes(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.bad = []

    def handle_starttag(self, tag, attrs):
        for name, _value in attrs:
            if not VALID_NAME.match(name):
                self.bad.append((self.getpos()[0], tag, name))


class NoPageHasAJunkAttribute(unittest.TestCase):

    def test_every_shipped_page_tokenises_into_real_attributes(self):
        pages = sorted(list(WEB.glob("*.html")) + list(WEB.glob("pages/*.html")))
        self.assertTrue(pages, "no pages found")
        offenders = []
        for page in pages:
            parser = _Attributes()
            parser.feed(page.read_text(encoding="utf-8"))
            offenders += [f"{page.relative_to(ROOT).as_posix()}:{line} <{tag}> has the "
                          f"attribute {name!r}" for line, tag, name in parser.bad]
        self.assertEqual([], offenders,
                         "an unescaped quote ended an attribute early:\n  "
                         + "\n  ".join(offenders))

    def test_the_check_can_fail(self):
        parser = _Attributes()
        parser.feed('<a title="says "quoted" things" href="/x">x</a>')
        self.assertTrue(parser.bad)


if __name__ == "__main__":
    unittest.main()
