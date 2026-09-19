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


class AMenuItemThatLeavesTheAppSaysWhereItGoes(unittest.TestCase):
    """"We need to change in the navigation bar 'View issues' to 'View issues
    on GitHub'."

    The two entries at the bottom of Help & Support are the only things in any
    menu that hand him to another website - one that needs an account he may
    not be signed into, on a machine whose network may not reach it. "View
    Issues" said none of that; it read like a panel inside the app.

    The rule is about the destination, not the wording: an item that opens an
    external site names that site. Nothing else in these menus leaves the app,
    so nothing else is caught by this.
    """

    EXTERNAL = re.compile(
        r'<a\s+class="(?:menu-item|help-menu-item)"([^>]*href="(https?://[^"]+)"[^>]*)>'
        r'(.*?)</a>', re.S)

    def _external_items(self):
        for path in sorted(WEB.rglob("*.html")):
            src = path.read_text(encoding="utf-8")
            for m in self.EXTERNAL.finditer(src):
                label = re.sub(r"<[^>]+>", "", m.group(3)).strip().lstrip("\u00b7 ")
                yield path.name, label, m.group(2), m.group(1)

    def test_the_issue_list_names_github(self):
        found = [(f, label) for f, label, href, _ in self._external_items()
                 if href.rstrip("/").endswith("/issues")]
        self.assertTrue(found, "the issue list link has gone")
        for filename, label in found:
            with self.subTest(page=filename):
                self.assertEqual("View Issues on GitHub", label)

    # A ratchet, not a gate - the same shape as the no-real-data baseline.
    #
    # **It is empty, and that is the point.** It held "Report a Bug", which had
    # exactly the gap he pointed at on its neighbour *View Issues* in v2.119.1:
    # the only two items in the suite that leave the app, both going to the same
    # GitHub repository, and only one of them saying so. It reads "Report a Bug
    # on GitHub" now, so the rule below applies to everything with nothing
    # excused from it. Putting a label back in here should take an argument
    # rather than a keystroke.
    LABELS_HE_HAS_NOT_RULED_ON: set = set()

    def test_every_outbound_item_names_the_site_it_opens(self):
        """Generalised, because the next one added would have the same gap."""
        for filename, label, href, _ in self._external_items():
            if label in self.LABELS_HE_HAS_NOT_RULED_ON:
                continue
            with self.subTest(page=filename, label=label):
                host = href.split("/")[2].lower()
                site = "GitHub" if "github" in host else host
                self.assertIn(site.lower(), label.lower(),
                              f"{label!r} opens {host} without saying so")

    def test_the_exemption_list_only_holds_labels_that_are_really_there(self):
        """A stale exemption is a rule quietly switched off. If he renames one
        of these, or it goes, this says so rather than leaving the entry to
        rot."""
        live = {label for _, label, _, _ in self._external_items()}
        stale = self.LABELS_HE_HAS_NOT_RULED_ON - live
        self.assertEqual(set(), stale,
                         f"exempted labels that no longer exist: {stale}")

    def test_an_outbound_item_opens_a_tab_rather_than_navigating_away(self):
        """Losing the page he was working on to a bug report is its own bug."""
        for filename, label, _, attrs in self._external_items():
            with self.subTest(page=filename, label=label):
                self.assertIn('target="_blank"', attrs)
                self.assertIn("noopener", attrs)


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
