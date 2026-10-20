"""Quick Walls offers to merge a wall type's copies into the original.

A project can hold the same wall type more than once - Ekahau's "(Copy)",
Quick Walls' own Clone, or the same name added beside an existing type. Each is
a card of its own and the walls drawn with it are counted apart. A notice above
the cards names them, and Merge moves their walls to the type that is kept and
removes the copy.

Run in the real page, by pressing the real buttons: what remains in the type
list, what the cards show, and which type each wall in the project file points
at after. Removing a type is the one thing here that cannot be undone in the
window, so the other half is that declining changes nothing and that a project
with no copies shows no notice. Names are invented.
"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
from collections import Counter
from pathlib import Path

from tests.test_squirrel_home_fits_the_screen import BrowserPagesHarness
from tests.test_strict_pages_work_in_a_browser import HAVE_SELENIUM
from tests.test_swap_lists_each_wall_type_once_browser import DRAWN, _esx

if HAVE_SELENIUM:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

ALL_IDS = {"wall-1", "door-1", "door-2", "win-1", "win-2", "win-copy",
           "win-copy2", "shelf-c1", "shelf-c2", "copy-wall"}

SEGMENT_TYPES = """
var done = arguments[arguments.length - 1];
window.esxZip.file('wallSegments.json').async('string').then(function (t) {
  done(JSON.parse(t).wallSegments.map(function (s) { return s.wallTypeId; }));
});
"""

STUB_CONFIRM = """
var answer = arguments[0];
window.__asked = [];
window.confirm = function (m) { window.__asked.push(m); return answer; };
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class MergingCopiesInQuickWalls(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.esx = _esx(Path(cls._tmp.name) / "invented-copies.esx")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._tmp.cleanup()

    def open_walls(self, drv):
        drv.set_window_size(1600, 1000)
        drv.get(self.base + "/walls")
        WebDriverWait(drv, 15).until(
            lambda d: d.find_elements(By.ID, "fileInput"))
        drv.find_element(By.ID, "fileInput").send_keys(str(self.esx))
        WebDriverWait(drv, 20).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, ".wall-card"))
        time.sleep(0.4)

    def ids(self, drv):
        return {t["id"] for t in drv.execute_script("return window.wallTypes;")}

    def names(self, drv):
        return {t["id"]: t["name"]
                for t in drv.execute_script("return window.wallTypes;")}

    def cards(self, drv):
        return len(drv.find_elements(By.CSS_SELECTOR, ".wall-card"))

    def segments(self, drv):
        return Counter(drv.execute_async_script(SEGMENT_TYPES))

    def press(self, drv, label):
        for b in drv.find_elements(By.CSS_SELECTOR, "#wallCopies button"):
            if b.text.strip() == label:
                b.click()
                time.sleep(0.6)
                return
        self.fail("no %r button in the notice" % label)

    def test_the_notice_names_the_copies_and_the_cards_are_all_there(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_walls(drv)
                panel = drv.find_element(By.ID, "wallCopies")
                self.assertTrue(panel.is_displayed())
                text = panel.text
                self.assertIn("5 wall types are copies of another", text)
                for name in ("Window, Invented C(Copy)(Copy)",
                             "Shelf, Invented D(Copy)(Copy)"):
                    self.assertIn(name, text)
                self.assertEqual(self.ids(drv), ALL_IDS)

    def test_declining_changes_nothing(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_walls(drv)
                before = self.segments(drv)
                drv.execute_script(STUB_CONFIRM, False)
                self.press(drv, "Merge all")
                self.assertEqual(len(drv.execute_script("return window.__asked;")), 1)
                self.assertEqual(self.ids(drv), ALL_IDS)
                self.assertEqual(self.segments(drv), before)

    def test_the_question_names_every_type_it_removes_with_its_walls(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_walls(drv)
                drv.execute_script(STUB_CONFIRM, False)
                self.press(drv, "Merge all")
                asked = drv.execute_script("return window.__asked[0];")
                for fragment in ('remove "Window, Invented C(Copy)" (4 walls)',
                                 'remove "Window, Invented C(Copy)(Copy)" (2 walls)',
                                 'remove "Shelf, Invented D(Copy)(Copy)" (1 wall)',
                                 'remove "Door, Invented B" (2 walls)',
                                 'Keep "Door, Invented B" (5 walls)'):
                    self.assertIn(fragment, asked)

    def test_merge_all_moves_every_wall_and_removes_every_copy(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_walls(drv)
                drv.execute_script(STUB_CONFIRM, True)
                self.press(drv, "Merge all")
                self.assertEqual(
                    self.ids(drv),
                    {"wall-1", "door-2", "win-1", "shelf-c1", "copy-wall"})
                self.assertEqual(self.segments(drv), Counter({
                    "wall-1": 3, "door-2": 7, "win-1": 9, "shelf-c1": 4,
                    "copy-wall": 1}))
                self.assertEqual(sum(self.segments(drv).values()), len(DRAWN))
                self.assertEqual(self.cards(drv), 5)
                self.assertFalse(
                    drv.find_element(By.ID, "wallCopies").is_displayed(),
                    "the notice stays up after nothing is left to merge")

    def test_a_kept_copy_with_no_original_loses_the_suffix(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_walls(drv)
                drv.execute_script(STUB_CONFIRM, True)
                self.press(drv, "Merge all")
                self.assertEqual(self.names(drv)["shelf-c1"], "Shelf, Invented D")

    def test_one_group_can_be_merged_on_its_own(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_walls(drv)
                drv.execute_script(STUB_CONFIRM, True)
                rows = drv.find_elements(By.CSS_SELECTOR, "#wallCopies .wall-audit-row")
                door = [r for r in rows
                        if r.find_elements(By.CSS_SELECTOR, ".wall-audit-name")
                        and r.find_element(By.CSS_SELECTOR, ".wall-audit-name").text
                        == "Door, Invented B"]
                self.assertEqual(len(door), 1)
                door[0].find_element(By.TAG_NAME, "button").click()
                time.sleep(0.6)
                self.assertEqual(self.ids(drv), ALL_IDS - {"door-1"})
                got = self.segments(drv)
                self.assertEqual(got["door-2"], 7)
                self.assertEqual(got["win-copy"], 4, "another group was touched")


if __name__ == "__main__":
    unittest.main()
