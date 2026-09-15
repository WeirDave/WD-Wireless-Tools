"""Every tool reachable from every page, and every menu button that opens one.

Two faults, both found by opening each page in Firefox and clicking the real
button rather than by reading the markup.

**Capacity was in 2 of 17 menus and Prep in 2 of 17.** Someone on the Report
page had no way to reach Prep at all short of typing the URL or going Home
first. A source grep would not have caught it either: three of the menus spell
their entries `help-menu-item` and the rest `menu-item`, so a search for one
class quietly reports the other's pages as having no menu.

**The Rename page's hamburger did nothing.** `rename.html` carried
`<button class="hamburger-btn" id="menuBtn">` with no `onclick`, and the
`getElementById('menuBtn')` listener that drives that markup lives in
`organizer.js` - which that page does not load. The button rendered, took the
click and there was no error anywhere. This is the repeated shape in this repo:
a control that is present and inert.

So this file asserts both halves - the links are there, and something is wired
to open the menu that holds them.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "web"

# Every tool a person can navigate to. Setup is excluded: it is the first-run
# screen and deliberately offers no way out but finishing.
TOOLS = {
    "/": "Home",
    "/cloud": "Cloud Manager",
    "/walls": "Quick Walls",
    "/report": "Report",
    "/scale": "Scale",
    "/plantrim": "PlanTrim",
    "/aprename": "AP Labeler",
    "/capacity": "Capacity",
    "/prep": "Prep",
    "/squirrel": "Squirrel",
    "/settings": "Suite Settings",
}

# Pages with no navigation menu at all, and why that is correct.
NO_MENU = {"setup.html"}

MENU_BLOCK = re.compile(
    r'<div[^>]*class="(?:main-menu|help-menu)"[^>]*>|'
    r'<div[^>]*class="(?:main-menu|help-menu)"[^>]*id="[^"]*"[^>]*>|'
    r'<div[^>]*id="[^"]*"[^>]*class="(?:main-menu|help-menu)"[^>]*>')

ITEM = re.compile(r'<a class="(?:menu-item|help-menu-item)(?: active)?" '
                  r'href="([^"]+)"')


def menu_blocks(text: str) -> list[str]:
    """Each menu's markup, from its opening div to the div that closes it."""
    blocks = []
    for m in MENU_BLOCK.finditer(text):
        start = m.end()
        # Menus are flat lists of <a>/<button>/<div class="menu-*"> lines; the
        # first line that closes a div at the menu's own nesting ends it.
        depth = 1
        i = start
        while i < len(text) and depth:
            nxt_open = text.find("<div", i)
            nxt_close = text.find("</div>", i)
            if nxt_close < 0:
                break
            if 0 <= nxt_open < nxt_close:
                depth += 1
                i = nxt_open + 4
            else:
                depth -= 1
                i = nxt_close + 6
        blocks.append(text[start:i])
    return blocks


def pages_with_menus():
    for f in sorted(WEB.glob("*.html")):
        if f.name in NO_MENU:
            continue
        yield f, f.read_text(encoding="utf-8")


class EveryToolIsInEveryMenu(unittest.TestCase):

    def test_each_menu_lists_every_tool(self):
        """A menu that lists some tools has to list all of them. A page whose
        menu is missing one is a dead end for that tool."""
        for f, text in pages_with_menus():
            for n, block in enumerate(menu_blocks(text)):
                hrefs = {h.split("#")[0] for h in ITEM.findall(block)}
                if not hrefs:
                    continue          # a menu of buttons only, not navigation
                if "/cloud" not in hrefs and "/walls" not in hrefs:
                    continue          # not the navigation menu
                missing = sorted(TOOLS[t] for t in TOOLS if t not in hrefs)
                with self.subTest(page=f.name, menu=n):
                    self.assertEqual(
                        missing, [],
                        f"{f.name} menu {n} cannot reach: {', '.join(missing)}")

    def test_every_page_has_a_navigation_menu(self):
        for f, text in pages_with_menus():
            with self.subTest(page=f.name):
                self.assertTrue(
                    any("/cloud" in b or "/walls" in b for b in menu_blocks(text)),
                    f"{f.name} has no navigation menu")


class EveryMenuButtonIsWiredToSomething(unittest.TestCase):
    """The Rename page's button had markup and no handler. A button that takes
    a click and does nothing produces no error, so only this catches it."""

    BTN = re.compile(r'<button[^>]*class="hamburger-btn"[^>]*>')

    def test_each_hamburger_has_a_handler_or_a_listener(self):
        # Which scripts each page loads, so an id-based listener can be
        # attributed to a file that page actually pulls in.
        for f, text in pages_with_menus():
            scripts = re.findall(r'<script src="([^"]+)"', text)
            loaded = ""
            for src in scripts:
                p = ROOT / "web" / src.lstrip("/")
                if p.exists():
                    loaded += p.read_text(encoding="utf-8")
            for btn in self.BTN.findall(text):
                with self.subTest(page=f.name, button=btn[:60]):
                    if "onclick=" in btn:
                        continue
                    bid = re.search(r'id="([^"]+)"', btn)
                    self.assertIsNotNone(
                        bid, f"{f.name}: hamburger with neither onclick nor id")
                    self.assertIn(
                        f"getElementById('{bid.group(1)}')", loaded,
                        f"{f.name}: button id={bid.group(1)} has no onclick and "
                        f"no listener in any script this page loads")


if __name__ == "__main__":
    unittest.main()
