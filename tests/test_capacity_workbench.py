"""Capacity in the workbench shell.

Part of the suite-wide refresh after the shell was seen in Prep: "this style
of layout is probably absolutely how the rest of the tools should look as
well". Capacity has no plan to draw on, so its three steps fill the middle
column; the rail jumps between them, and "Apply and download" sits in the
footer, which never scrolls away, beside the sentence saying what it will do.

Read from the page as the browser builds it:

* every step on the rail points at a card that exists - a rail entry that
  goes nowhere is a control that does nothing. What pressing one does is
  driven in a browser by `test_capacity_steps_browser.py`;
* the footer is outside the scrolling column, and holds the button and its
  note.
"""
from __future__ import annotations

import unittest
from html.parser import HTMLParser
from pathlib import Path

HTML = Path(__file__).resolve().parent.parent / "web" / "capacity.html"


class _Page(HTMLParser):
    VOID = {"input", "br", "img", "meta", "link", "hr", "source"}

    def __init__(self):
        super().__init__()
        self.stack, self.ids, self.jumps, self.where = [], set(), [], {}

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        name = d.get("id") or (d.get("class") or "").split(" ")[0] or tag
        if d.get("id"):
            self.ids.add(d["id"])
            self.where[d["id"]] = list(self.stack)
        if d.get("data-fn") == "capGoTo":
            self.jumps.append((d.get("data-arg"), list(self.stack)))
        if tag == "footer":
            self.where["<footer>"] = list(self.stack)
        if tag not in self.VOID:
            self.stack.append(name)

    def handle_endtag(self, tag):
        if tag not in self.VOID and self.stack:
            self.stack.pop()


def _page():
    p = _Page()
    p.feed(HTML.read_text(encoding="utf-8"))
    return p


class CapacityShell(unittest.TestCase):
    def test_the_rail_has_the_three_steps(self):
        on_rail = [t for t, stack in _page().jumps if "pb-rail" in stack]
        # The template comes first: picking it is the everyday job, and it
        # is preselected from the default.
        self.assertEqual(on_rail, ["capStepTpl", "capStep3", "capStep1"])

    def test_every_step_points_at_a_card_that_exists(self):
        p = _page()
        for target, _ in p.jumps:
            with self.subTest(target=target):
                self.assertIn(target, p.ids)
                self.assertIn("pb-main", p.where[target], "the card is not in the steps column")

    def test_the_verb_and_its_note_are_in_the_footer(self):
        w = _page().where
        for ident in ("capApplyBtn", "capApplyNote"):
            with self.subTest(id=ident):
                self.assertIn("pb-footer", w[ident])

    def test_the_footer_is_outside_the_scrolling_column(self):
        w = _page().where
        self.assertNotIn("pb-main", w["<footer>"])
        self.assertNotIn("pb-body", w["<footer>"])


if __name__ == "__main__":
    unittest.main()
