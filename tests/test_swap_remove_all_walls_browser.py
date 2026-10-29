"""Visual Swap's "Remove all walls", driven in a real browser.

The panel clears every wall on the floor in view, or every wall in the project,
whatever is selected. It shares its delete path with "Delete selected", so what
is pinned here is the part that is new: the scope, the count on the button, the
confirm, and that one Undo puts back every wall *and* every wall point it freed.

Each case clicks the real button on the real /walls page, on the same invented
three-floor project the other Visual Swap browser tests use (floor one holds six
walls, floor two holds two, floor three holds none).
"""
from __future__ import annotations

import unittest

from tests.test_strict_pages_work_in_a_browser import HAVE_SELENIUM
from tests.test_walls_swap_floors_points_and_hover_browser import S, _SwapPage

if HAVE_SELENIUM:
    from selenium.webdriver.common.by import By


def _button(drv):
    return drv.find_element(By.ID, "swapRemoveAllBtn")


def _label(drv):
    return " ".join(_button(drv).text.split())


def _click_remove(drv):
    drv.execute_script(
        "document.getElementById('swapRemoveAllBtn').scrollIntoView({block:'center'});")
    _button(drv).click()


def _set_scope(drv, scope):
    drv.execute_script(
        "var s = document.getElementById('swapRemoveScope'); s.value = arguments[0];"
        "s.dispatchEvent(new Event('change', {bubbles: true}));", scope)


def _written_ids(page, drv):
    return sorted(s["id"] for s in page.zipjson(drv, "wallSegments.json")["wallSegments"])


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class RemoveAllWallsOnThisFloor(_SwapPage):

    def test_only_the_floor_in_view_is_cleared_and_undo_restores_it_exactly(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_swap(drv)
                segs_before = self.zipjson(drv, "wallSegments.json")
                points_before = self.zipjson(drv, "wallPoints.json")
                self.assertEqual(drv.execute_script(S + "getFloor()"), "f1")
                self.assertEqual(
                    drv.execute_script("return document.getElementById('swapRemoveScope').value;"),
                    "floor", "the safe scope has to be the default")
                self.assertEqual(_label(drv), "Remove all 6 walls on this floor")

                # A selection that covers only some walls must not narrow it.
                drv.execute_script("__wallsSwap.marqueeWorld(90, 90, 200, 110);")
                self.assertEqual(drv.execute_script(S + "getSelected()"), ["s1"])

                _click_remove(drv)

                self.assertEqual(drv.execute_script(S + "getFloorSegIds()"), [])
                self.assertEqual(drv.execute_script(S + "getSelected()"), [])
                self.assertEqual(_written_ids(self, drv), ["t1", "t2"])
                # Every point only floor one's walls used goes; floor two's stay.
                left = {p["id"] for p in self.zipjson(drv, "wallPoints.json")["wallPoints"]}
                self.assertEqual(left, {"q1", "q2", "q3"})
                self.assertEqual(_label(drv), "No walls on this floor")
                self.assertFalse(_button(drv).is_enabled())
                self.assertIn("— 0 walls", drv.execute_script(
                    "return document.getElementById('swapFloorSelect').selectedOptions[0].text;"))

                drv.execute_script("swapUndo();")
                self.assertEqual(self.zipjson(drv, "wallSegments.json"), segs_before)
                self.assertEqual(self.zipjson(drv, "wallPoints.json"), points_before)
                self.assertEqual(_label(drv), "Remove all 6 walls on this floor")

                drv.execute_script("swapRedo();")
                self.assertEqual(_written_ids(self, drv), ["t1", "t2"])
                drv.execute_script("swapUndo();")
                self.assertEqual(self.zipjson(drv, "wallSegments.json"), segs_before)

    def test_walls_with_no_type_or_a_deleted_type_go_too(self):
        """s5 has no type and s6's type is gone; neither may be spared."""
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_swap(drv)
                _click_remove(drv)
                self.assertNotIn("s5", _written_ids(self, drv))
                self.assertNotIn("s6", _written_ids(self, drv))

    def test_a_declined_confirm_removes_nothing(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_swap(drv)
                drv.execute_script(
                    "window.__asked = null;"
                    "window.confirm = function (m) { window.__asked = m; return false; };")
                _click_remove(drv)
                asked = drv.execute_script("return window.__asked;")
                self.assertIn("6 walls", asked or "", "the dialog has to say how many")
                self.assertEqual(len(_written_ids(self, drv)), 8)
                self.assertEqual(drv.execute_script(S + "getSegmentCount()"), 8)

    def test_a_floor_with_no_walls_offers_nothing_and_says_why(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_swap(drv)
                self.pick_floor(drv, "f3")
                self.assertEqual(_label(drv), "No walls on this floor")
                self.assertFalse(_button(drv).is_enabled())
                self.pick_floor(drv, "f2")
                self.assertEqual(_label(drv), "Remove all 2 walls on this floor")
                self.assertTrue(_button(drv).is_enabled())


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class RemoveAllWallsInTheWholeProject(_SwapPage):

    def test_every_floor_is_cleared_and_one_undo_brings_all_back(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_swap(drv)
                segs_before = self.zipjson(drv, "wallSegments.json")
                points_before = self.zipjson(drv, "wallPoints.json")
                self.pick_floor(drv, "f2")

                _set_scope(drv, "project")
                self.assertEqual(_label(drv), "Remove all 8 walls in the whole project")
                drv.execute_script(
                    "window.__asked = null;"
                    "window.confirm = function (m) { window.__asked = m; return true; };")
                _click_remove(drv)

                asked = drv.execute_script("return window.__asked;")
                for part in ("8 walls", "Invented One: 6 walls", "Invented Two: 2 walls"):
                    self.assertIn(part, asked)
                self.assertEqual(_written_ids(self, drv), [])
                self.assertEqual(drv.execute_script(S + "getSegmentCount()"), 0)
                self.assertEqual(self.zipjson(drv, "wallPoints.json")["wallPoints"], [])
                self.assertEqual(_label(drv), "No walls in the whole project")

                drv.execute_script("swapUndo();")
                self.assertEqual(self.zipjson(drv, "wallSegments.json"), segs_before)
                self.assertEqual(self.zipjson(drv, "wallPoints.json"), points_before)
                self.assertEqual(drv.execute_script(S + "getSegmentCount()"), 8)

    def test_changing_scope_changes_the_count_on_the_button(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_swap(drv)
                self.assertEqual(_label(drv), "Remove all 6 walls on this floor")
                _set_scope(drv, "project")
                self.assertEqual(_label(drv), "Remove all 8 walls in the whole project")
                _set_scope(drv, "floor")
                self.assertEqual(_label(drv), "Remove all 6 walls on this floor")


if __name__ == "__main__":
    unittest.main()
