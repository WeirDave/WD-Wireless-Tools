"""Cloud Manager's header: three bands, each with one job.

"as I said, better UX is required because it's just a lot in a little amount of
space" - and then "no, but you can make a drop down and redesign the whole
thing."

The old header put everything on screen at once: seventeen filter cards, nine
of them visible, and twenty-three toolbar controls. Intrinsic width 2342px, so
it only ever fitted a 2560 monitor; v2.112.3 stopped it being clipped by
wrapping it, which made it legible without making it less.

What replaced it:

* **A summary line.** The counts are information first and filters second, so
  they read as a sentence instead of nine chips competing with the bar below.
  The rarely-used ones moved into "More filters".
* **A short toolbar** of what he reaches for constantly, plus named dropdowns
  for the sets.
* **A selection bar** that is not in the document until something is ticked.
  Half the old toolbar meant nothing with an empty selection, and it was the
  half - about 900px of it - that pushed everything else off a laptop screen.

Measured in Firefox at 1366, 1440, 1920 and 2560: **0 clipped at every width**,
and each of the three bands is a single line even at 1366. The menus were
driven rather than read - all four open on a click, fire their item's handler,
land on screen, close afterwards, and close on Escape.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
HTML = (ROOT / "web" / "cloud.html").read_text(encoding="utf-8")
CSS = (ROOT / "web" / "assets" / "wd-tools.css").read_text(encoding="utf-8")
JS = (ROOT / "web" / "assets" / "js" / "cloud.js").read_text(encoding="utf-8")

SELECTION_ONLY = [
    "bulkSyncTo", "bulkSyncFrom", "compareBtn", "bulkMoveBtn",
    "bulkShareBtn", "bulkVerifyBtn", "bulkDeleteBtn",
]


def band(name: str) -> str:
    """The markup of one header band."""
    start = HTML.index('<div class="%s"' % name)
    depth, i = 0, start
    while True:
        nxt = min((x for x in (HTML.find("<div", i + 1), HTML.find("</div>", i + 1))
                   if x != -1), default=-1)
        if nxt == -1:
            raise AssertionError("unbalanced " + name)
        if HTML.startswith("<div", nxt):
            depth += 1
        else:
            if depth == 0:
                return HTML[start:nxt]
            depth -= 1
        i = nxt


class NothingWasLostInTheRestructureTests(unittest.TestCase):
    """The rebuild moved controls; it must not have dropped any.

    Every id is load-bearing: `updateCounts` writes the numbers by id and
    `updateBulkBar` enables and disables the actions by id, so keeping them is
    what made this a layout change rather than a rewrite.
    """

    COUNTERS = ["dAll", "dStale", "dMismatches", "dNameMatches", "dOrphans",
                "dExternal", "dUnshared", "dCloudOnly", "dLocalOnly",
                "dUnassigned", "dTypeDesign", "dTypeMeasured", "dTypeHybrid",
                "dDupAll", "dDupCloud", "dDupLocal", "dDupMixed"]

    ACTIONS = ["searchBox", "syncAllBtn", "selAll", "selCount", "expandAllBtn",
               "collapseAllBtn", "matchHelpChip", "ownerToggle", "addNewBtn",
               "liveBtn"] + SELECTION_ONLY

    def test_every_counter_survived(self):
        for i in self.COUNTERS:
            with self.subTest(counter=i):
                self.assertIn('id="%s"' % i, HTML)

    def test_every_action_survived(self):
        for i in self.ACTIONS:
            with self.subTest(action=i):
                self.assertIn('id="%s"' % i, HTML)

    def test_every_filter_still_says_what_it_selects(self):
        """"I forgot what hybrid meant, or external for that matter." The
        restructure dropped these once; a test caught it."""
        controls = re.findall(
            r'<button class="sum-count"[^>]*?data-filter="([a-z-]+)"([^>]*)>', HTML)
        self.assertEqual(17, len(controls))
        for key, attrs in controls:
            with self.subTest(filter=key):
                self.assertIn("title=", attrs)

    def test_every_filter_shows_its_count(self):
        """The reason the dropdown had to go.

        "29 out of sync, 5 name matches" is what tells him where his work is
        before he clicks anything, and a menu shows none of it until opened.
        A filter without its number on it is a filter that has stopped doing
        its job.
        """
        chips = re.findall(r'<button class="sum-count".*?</button>', HTML, re.S)
        self.assertEqual(17, len(chips))
        for chip in chips:
            label = re.search(r'<span class="sum-l">([^<]+)</span>', chip)
            with self.subTest(chip=(label.group(1) if label else chip[:40])):
                self.assertRegex(chip, r'<span class="sum-n" id="d[A-Za-z]+">')
                self.assertIsNotNone(label, "a chip with a number and no words")


class TheSelectionBarIsNotThereUntilItIsNeededTests(unittest.TestCase):

    def test_it_starts_hidden(self):
        self.assertIn('<div class="selection-bar" id="selectionBar" hidden>', HTML)

    def test_it_is_shown_and_hidden_by_the_selection(self):
        block = JS[JS.index("function updateBulkBar()"):]
        block = block[:block.index("\n}")]
        self.assertIn("getElementById('selectionBar')", block)
        self.assertIn("hidden = n === 0", block)

    def test_the_selection_actions_live_there_and_not_in_the_toolbar(self):
        """This is the ~900px that made the old bar unfittable. If one of them
        drifts back into the resting toolbar, it comes back."""
        bar = band("toolbar")
        sel = band("selection-bar")
        for i in SELECTION_ONLY:
            with self.subTest(action=i):
                self.assertNotIn('id="%s"' % i, bar)
                self.assertIn('id="%s"' % i, sel)


class TheDropdownsAreUsableTests(unittest.TestCase):

    def test_they_are_native_details_elements(self):
        """`<details>` opens on a click and is keyboard reachable for free.
        Nothing here appears on hover: hover-to-reveal would break the standing
        rule about decision-relevant information being visible at rest."""
        self.assertGreaterEqual(len(re.findall(r'<details class="wd-menu[ "]', HTML)), 2)
        self.assertNotIn(".wd-menu:hover .wd-menu-items", CSS)

    def test_no_filter_is_behind_a_menu(self):
        """The counts are the point, and a menu hides them until it is opened.

        "some buttons where the highlights don't move, and other filters in a
        dropdown where you can't tell which filter you're on. That whole system
        is clunky at best."

        Half the filters wearing their counts and half hiding them is the
        hybrid he was describing. Select and View stay dropdowns - they hold
        actions, which have nothing to show at rest - but a filter carries a
        number he reads before deciding, so it is always a chip.
        """
        # Stated as "every filter is a chip" rather than as two absences:
        # a string not appearing is weak evidence, and the thing that matters
        # is what each filter *is*, not what the markup no longer says.
        carriers = re.findall(r'<(\w+) class="([^"]*)"[^>]*data-filter=', HTML)
        self.assertEqual(17, len(carriers))
        for tag, classes in carriers:
            with self.subTest(carrier=classes):
                self.assertEqual("button", tag)
                self.assertIn("sum-count", classes.split())
                self.assertNotIn("wd-menu-item", classes.split())

    def test_the_menus_are_named_in_words(self):
        """A dropdown full of icons repeats the mistake that got the labels put
        on in the first place."""
        for name in ("Select", "View", "Move, share, overwrite"):
            with self.subTest(menu=name):
                self.assertIn(">%s</summary>" % name, HTML)

    def test_every_item_keeps_its_full_label(self):
        items = re.findall(r'<button class="wd-menu-item"[^>]*>(.*?)</button>',
                           HTML, re.S)
        # Ten of these were filters and became chips; what is left is Select
        # and View, which hold actions.
        self.assertGreater(len(items), 3)
        for text in items:
            plain = re.sub(r"<[^>]+>", "", text).strip()
            with self.subTest(item=plain[:30]):
                self.assertGreater(len(plain), 3, "an icon-only menu item")

    def test_a_menu_closes_after_something_in_it_is_chosen(self):
        """Otherwise it sits over the row the action just ran on."""
        self.assertIn(".wd-menu[open]", JS)
        self.assertIn("m.open = false", JS)
        self.assertIn("'Escape'", JS)

    def test_a_menu_near_the_right_edge_opens_inwards(self):
        self.assertIn(".selection-bar .wd-menu-items { left: auto; right: 0; }", CSS)


class TheHeaderStillFitsTests(unittest.TestCase):
    """The v2.112.3 guarantees survive the redesign."""

    def test_the_bands_still_wrap(self):
        for sel in ("body.tool-cloud .toolbar", ".summary-line", ".selection-bar"):
            with self.subTest(band=sel):
                blocks = [CSS[m.start():CSS.index("}", m.start())]
                          for m in re.finditer(re.escape(sel) + r"\s*\{", CSS)]
                self.assertTrue(any("flex-wrap: wrap" in b for b in blocks), sel)

    def test_nothing_shrinks_below_its_label(self):
        self.assertIn("body.tool-cloud .toolbar > * { flex-shrink: 0; }", CSS)
        self.assertIn(".selection-bar > * { flex-shrink: 0; }", CSS)

    def test_focus_is_visible_on_the_new_controls(self):
        self.assertIn(".sum-count:focus-visible", CSS)
        self.assertIn(".wd-menu-item:focus-visible", CSS)


if __name__ == "__main__":
    unittest.main()
