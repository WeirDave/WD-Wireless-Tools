"""Prep's stages are trim, areas and wall types - and not Wall Swap.

Suite 2.195.0 put a fourth stage, Wall swap, on Prep's rail. The maintainer
had it taken off: Prep gets a *new* project's `.esx` ready to work in, while
swapping wall types happens after the import, once it turns out the import
flattened concrete and steel onto one type. That stays in Quick Walls.

Read from the rendered markup: every stage the rail opens, and every panel the
page can show.
"""
from __future__ import annotations

import unittest
from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PREP_HTML = ROOT / "web" / "prep.html"


class _Stages(HTMLParser):
    def __init__(self):
        super().__init__()
        self.opened, self.panels, self.text = [], [], []

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if d.get("data-fn") == "prepStage" and d.get("data-arg"):
            self.opened.append(d["data-arg"])
        if (d.get("id") or "").startswith("prepPanel-"):
            self.panels.append(d["id"][len("prepPanel-"):])

    def handle_data(self, data):
        self.text.append(data)


def _read():
    p = _Stages()
    p.feed(PREP_HTML.read_text(encoding="utf-8"))
    return p


class PrepStages(unittest.TestCase):
    def test_the_rail_opens_trim_areas_and_walls_in_that_order(self):
        self.assertEqual(_read().opened, ["trim", "areas", "walls"])

    def test_every_stage_has_a_panel_and_there_is_no_other(self):
        p = _read()
        self.assertEqual(sorted(p.panels), sorted(p.opened))

    def test_no_text_on_the_page_offers_wall_swap(self):
        text = " ".join(" ".join(_read().text).split()).lower()
        self.assertNotIn("wall swap", text)


if __name__ == "__main__":
    unittest.main()
