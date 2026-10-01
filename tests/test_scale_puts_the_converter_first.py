"""Scale's converter sits just under the header, not behind its logo.

Part of the suite-wide refresh. Scale is a two-sided unit converter with no
file to open, so the workbench shell the file tools share has nothing to hold
there; what it needed was the tool above the fold. A 180px logo, a 26px title
and two lines of copy, stacked and centred, put both inputs half way down a
900px window. The title is now one compact row beside a small logo.

Measured in the cascade the browser applies (`tests/css_source.rule_for`), and
in Chromium during the change: the converter grid's top went from 435px to
188px at 1400x900.
"""
from __future__ import annotations

import re
import unittest

from tests.css_source import rule_for


def _px(rule: str, prop: str) -> float:
    m = re.search(prop + r"\s*:\s*([0-9.]+)px", rule)
    if not m:
        raise AssertionError("%s not set in px: %r" % (prop, rule))
    return float(m.group(1))


class TheConverterComesFirst(unittest.TestCase):
    def test_the_logo_is_small(self):
        self.assertLessEqual(_px(rule_for("scale.html", ".scale-hero-logo img"), "max-height"), 80)

    def test_the_logo_sits_beside_the_title_not_above_it(self):
        rule = rule_for("scale.html", ".scale-hero")
        self.assertRegex(rule, r"display:\s*grid")
        self.assertRegex(rule, r"grid-template-columns:\s*auto 1fr")


if __name__ == "__main__":
    unittest.main()
