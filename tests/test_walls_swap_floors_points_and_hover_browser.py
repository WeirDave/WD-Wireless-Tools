"""Visual Swap, driven in a real browser on an invented three-floor project.

Each class is one defect that shipped, and each drives the real /walls page:

* an undo of an edit made on another floor restored a selection nobody could
  see, and Delete then removed walls on the floor not shown;
* picking two floors quickly left the first floor's plan under the second
  floor's walls, because the slower image load finished last;
* the window-wide mousemove hit-tested the plan while the pointer was over the
  sidebar, wiping the hover a row had set and lighting walls off the canvas;
* Delete left wall points no remaining segment used in wallPoints.json;
* a sidebar width dragged after reopening snapped back on a window resize;
* walls with no wall type were labelled "(deleted wall type)" and their legend
  row selected nothing.
"""
from __future__ import annotations

import io
import json
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

from tests.test_squirrel_home_fits_the_screen import BrowserPagesHarness
from tests.test_strict_pages_work_in_a_browser import HAVE_SELENIUM

if HAVE_SELENIUM:
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.actions.action_builder import ActionBuilder
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait


def _png(w, h):
    from PIL import Image
    b = io.BytesIO()
    Image.new("RGB", (w, h), "white").save(b, "PNG")
    return b.getvalue()


def _esx(path):
    types = [("wt-a", "Wall, Invented A", "#C9A27A"),
             ("wt-b", "Door, Invented B", "#8B5A2B"),
             ("wt-c", "Window, Invented C", "#0093EA")]
    pts = []

    def P(pid, fid, x, y):
        pts.append({"id": pid, "location": {"floorPlanId": fid,
                                            "coord": {"x": x, "y": y}}})
    # Floor f1. s1 and s2 share p2; s5 has no type; s6's type was deleted.
    P("p1", "f1", 100, 100); P("p2", "f1", 300, 100); P("p3", "f1", 300, 300)
    P("p4", "f1", 500, 500); P("p5", "f1", 700, 500)
    P("p6", "f1", 100, 600); P("p7", "f1", 200, 600)
    P("p8", "f1", 800, 100); P("p9", "f1", 900, 100)
    P("p10", "f1", 800, 700); P("p11", "f1", 900, 700)
    segs = [
        {"id": "s1", "wallPoints": ["p1", "p2"], "wallTypeId": "wt-a"},
        {"id": "s2", "wallPoints": ["p2", "p3"], "wallTypeId": "wt-a"},
        {"id": "s3", "wallPoints": ["p4", "p5"], "wallTypeId": "wt-b"},
        {"id": "s4", "wallPoints": ["p6", "p7"], "wallTypeId": "wt-c"},
        {"id": "s5", "wallPoints": ["p8", "p9"]},
        {"id": "s6", "wallPoints": ["p10", "p11"], "wallTypeId": "wt-gone"},
    ]
    P("q1", "f2", 100, 100); P("q2", "f2", 600, 100); P("q3", "f2", 600, 600)
    segs += [
        {"id": "t1", "wallPoints": ["q1", "q2"], "wallTypeId": "wt-a"},
        {"id": "t2", "wallPoints": ["q2", "q3"], "wallTypeId": "wt-b"},
    ]
    floors = [
        {"id": "f1", "name": "Invented One", "imageId": "img1",
         "width": 1000, "height": 800, "metersPerUnit": 0.05},
        {"id": "f2", "name": "Invented Two", "imageId": "img2",
         "width": 2000, "height": 1000, "metersPerUnit": 0.1},
        {"id": "f3", "name": "Invented Three", "imageId": "img3",
         "width": 400, "height": 1200, "metersPerUnit": 0.02},
    ]
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("project.json", json.dumps(
            {"project": {"id": "proj-invented-floors", "name": "Invented Floors"}}))
        zf.writestr("floorPlans.json", json.dumps({"floorPlans": floors}))
        zf.writestr("images.json", json.dumps({"images": [
            {"id": i, "imageFormat": "PNG"} for i in ("img1", "img2", "img3")]}))
        zf.writestr("wallTypes.json", json.dumps({"wallTypes": [
            {"id": i, "name": n, "color": c, "thickness": 0.1,
             "attenuations": []} for i, n, c in types]}))
        zf.writestr("wallPoints.json", json.dumps({"wallPoints": pts}))
        zf.writestr("wallSegments.json", json.dumps({"wallSegments": segs}))
        zf.writestr("image-img1", _png(1000, 800))
        zf.writestr("image-img2", _png(2000, 1000))
        zf.writestr("image-img3", _png(400, 1200))
    return path, pts


S = "return window.__wallsSwap."


class _SwapPage(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.esx, cls.points = _esx(Path(cls._tmp.name) / "invented-floors.esx")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._tmp.cleanup()

    def open_swap(self, drv):
        drv.set_window_size(1600, 1000)
        drv.get(self.base + "/walls")
        WebDriverWait(drv, 15).until(
            lambda d: d.find_elements(By.ID, "fileInput"))
        drv.find_element(By.ID, "fileInput").send_keys(str(self.esx))
        WebDriverWait(drv, 20).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, ".wall-card"))
        drv.execute_script(
            "window.confirm = function () { return true; }; openSwapModal();")
        WebDriverWait(drv, 20).until(lambda d: d.execute_script(
            "return !!(window.__wallsSwap && window.__wallsSwap.getSegmentCount()"
            " && window.__wallsSwap.getFitScale() > 0);"))

    def zipjson(self, drv, name):
        return drv.execute_async_script(
            "var cb = arguments[arguments.length - 1];"
            "window.esxZip.file(arguments[0]).async('string')"
            ".then(function (s) { cb(JSON.parse(s)); });", name)

    def pick_floor(self, drv, fid):
        drv.execute_script(
            "document.getElementById('swapFloorSelect').value = arguments[0];"
            "onSwapFloorChange();", fid)
        WebDriverWait(drv, 10).until(lambda d: d.execute_script(
            S + "getFitScale() > 0 && window.__wallsSwap.getFloor() === arguments[0];",
            fid))


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class UndoOnAnotherFloorShowsWhatItUndid(_SwapPage):

    def test_undo_goes_back_to_the_floor_and_delete_only_sees_that_floor(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_swap(drv)
                self.assertEqual(drv.execute_script(S + "getFloor()"), "f1")
                drv.execute_script("__wallsSwap.marqueeWorld(50, 50, 350, 350);")
                self.assertEqual(sorted(drv.execute_script(S + "getSelected()")),
                                 ["s1", "s2"])
                drv.execute_script(
                    "document.getElementById('swapTargetType').value = 'wt-b';"
                    "onSwapTargetChange(); applySelectionSwap();")
                self.pick_floor(drv, "f2")
                drv.execute_script("swapUndo();")
                WebDriverWait(drv, 10).until(lambda d: d.execute_script(
                    S + "getFloor() === 'f1' && window.__wallsSwap.getFitScale() > 0"))
                time.sleep(0.2)

                types = {t["id"]: t["type"] for t in
                         drv.execute_script(S + "getSegTypes()")}
                self.assertEqual((types["s1"], types["s2"]), ("wt-a", "wt-a"))
                self.assertEqual(drv.execute_script(
                    "return document.getElementById('swapFloorSelect').value;"), "f1")
                on_floor = set(drv.execute_script(S + "getFloorSegIds()"))
                selected = drv.execute_script(S + "getSelected()")
                self.assertEqual(sorted(selected), ["s1", "s2"])
                self.assertLessEqual(set(selected), on_floor)
                # The list shows what the button counts.
                rows = drv.execute_script(
                    "return [...document.querySelectorAll('#swapSelBreakdown"
                    " .swap-seg-row')].map(r => r.getAttribute('data-seg-id'));")
                self.assertEqual(sorted(rows), ["s1", "s2"])

                # Redo from yet another floor lands on f1 too, with the
                # selection on the walls it changed.
                self.pick_floor(drv, "f2")
                drv.execute_script("swapRedo();")
                WebDriverWait(drv, 10).until(lambda d: d.execute_script(
                    S + "getFloor() === 'f1' && window.__wallsSwap.getFitScale() > 0"))
                time.sleep(0.2)
                types = {t["id"]: t["type"] for t in
                         drv.execute_script(S + "getSegTypes()")}
                self.assertEqual((types["s1"], types["s2"]), ("wt-b", "wt-b"))
                selected = drv.execute_script(S + "getSelected()")
                self.assertEqual(sorted(selected), ["s1", "s2"])
                self.assertLessEqual(
                    set(selected), set(drv.execute_script(S + "getFloorSegIds()")))


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class AStaleFloorLoadDoesNotWin(_SwapPage):

    # Holds the first image created back by 600 ms, so the floor picked first
    # always finishes decoding last - the order the defect needed, every run.
    SLOW_FIRST_IMAGE = """
      var Real = window.__realImage || (window.__realImage = window.Image);
      var made = 0;
      window.Image = function () {
        var img = new Real(), k = made++, handler = null;
        Object.defineProperty(img, 'onload', {
          configurable: true,
          get: function () { return handler; },
          set: function (fn) {
            handler = fn;
            img.addEventListener('load', function () {
              setTimeout(function () { if (handler) handler(); }, k === 0 ? 600 : 0);
            });
          }
        });
        return img;
      };"""

    def test_the_floor_picked_last_keeps_its_own_plan(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_swap(drv)
                drv.execute_script(self.SLOW_FIRST_IMAGE)
                try:
                    drv.execute_script(
                        "var sel = document.getElementById('swapFloorSelect');"
                        "sel.value = 'f2'; onSwapFloorChange();"
                        "sel.value = 'f3'; onSwapFloorChange();")
                    time.sleep(1.5)
                finally:
                    drv.execute_script("window.Image = window.__realImage;")
                self.assertEqual(drv.execute_script(S + "getFloor()"), "f3")
                plan = drv.execute_script(S + "getPlan()")
                self.assertEqual((plan["w"], plan["h"], plan["imageWidth"]),
                                 (400, 1200, 400))


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class TheSidebarDoesNotDriveThePlanHover(_SwapPage):

    def test_moving_within_a_row_keeps_that_rows_wall_lit(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_swap(drv)
                drv.execute_script(
                    "__wallsSwap.selectAll(); expandAllSwapGroups();")
                row = drv.find_element(By.CSS_SELECTOR,
                                       ".swap-seg-row .swap-seg-locate")
                rid = drv.execute_script(
                    "return arguments[0].closest('.swap-seg-row')"
                    ".getAttribute('data-seg-id');", row)
                ActionChains(drv).move_to_element(row).perform()
                time.sleep(0.2)
                self.assertEqual(drv.execute_script(S + "getHover().seg"), rid)
                ActionChains(drv).move_by_offset(3, 0).perform()
                time.sleep(0.2)
                self.assertEqual(drv.execute_script(S + "getHover().seg"), rid)

    def test_a_wall_panned_under_the_sidebar_is_not_lit_by_the_pointer(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_swap(drv)
                # Pan s3's midpoint (600, 500) to a point over the sidebar.
                res = drv.execute_script("""
                  var cv = document.getElementById('swapCanvas');
                  var c = cv.getBoundingClientRect();
                  var sb = document.getElementById('swapSidebar').getBoundingClientRect();
                  for (var i = 0; i < 10; i++) zoomIn();
                  var v = __wallsSwap.getView();
                  var tx = sb.left + 80, ty = sb.top + 300;
                  var nowX = c.left + 600 * v.scale + v.x, nowY = c.top + 500 * v.scale + v.y;
                  var sx = c.left + 200, sy = c.top + 200;
                  var ex = sx + (tx - nowX), ey = sy + (ty - nowY);
                  cv.dispatchEvent(new MouseEvent('mousedown', {button: 2, clientX: sx, clientY: sy, bubbles: true}));
                  window.dispatchEvent(new MouseEvent('mousemove', {clientX: ex, clientY: ey}));
                  window.dispatchEvent(new MouseEvent('mouseup', {button: 2, clientX: ex, clientY: ey}));
                  return {tx: tx, ty: ty, s3: __wallsSwap.hitAtWorld(
                    (tx - c.left - __wallsSwap.getView().x) / __wallsSwap.getView().scale,
                    (ty - c.top - __wallsSwap.getView().y) / __wallsSwap.getView().scale)};""")
                # The setup is only meaningful if s3 really lies under that point.
                self.assertEqual(res["s3"], "s3")
                ab = ActionBuilder(drv)
                ab.pointer_action.move_to_location(int(res["tx"]), int(res["ty"]))
                ab.perform()
                time.sleep(0.3)
                self.assertIsNone(drv.execute_script(S + "getHover().seg"))
                self.assertEqual(drv.execute_script(S + "getHighlighted()"), [])


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class DeleteTakesTheWallPointsItFrees(_SwapPage):

    def test_freed_points_go_shared_ones_stay_and_undo_puts_them_back(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_swap(drv)
                original = self.zipjson(drv, "wallPoints.json")["wallPoints"]
                self.assertEqual(original, self.points)
                drv.execute_script("__wallsSwap.marqueeWorld(90, 90, 200, 110);")
                self.assertEqual(drv.execute_script(S + "getSelected()"), ["s1"])
                drv.execute_script("deleteSelectedWalls();")
                after = [p["id"] for p in
                         self.zipjson(drv, "wallPoints.json")["wallPoints"]]
                # p1 was s1's alone; p2 is still s2's.
                self.assertNotIn("p1", after)
                self.assertIn("p2", after)
                self.assertEqual(len(after), len(original) - 1)

                drv.execute_script("swapUndo();")
                self.assertEqual(
                    self.zipjson(drv, "wallPoints.json")["wallPoints"], original)
                drv.execute_script("swapRedo();")
                self.assertEqual([p["id"] for p in self.zipjson(
                    drv, "wallPoints.json")["wallPoints"]], after)
                drv.execute_script("swapUndo();")
                self.assertEqual(
                    self.zipjson(drv, "wallPoints.json")["wallPoints"], original)


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class ADraggedSidebarWidthSurvivesAReopen(_SwapPage):

    DRAG = """
      var sp = document.getElementById('swapSplitter').getBoundingClientRect();
      var x = sp.left + 2, y = sp.top + 50;
      document.getElementById('swapSplitter').dispatchEvent(
        new MouseEvent('mousedown', {clientX: x, clientY: y, bubbles: true}));
      window.dispatchEvent(new MouseEvent('mousemove', {clientX: x - 120, clientY: y}));
      window.dispatchEvent(new MouseEvent('mouseup', {clientX: x - 120, clientY: y}));
      return __wallsSwap.getSidebarWidth();"""

    def test_a_width_dragged_after_reopening_is_kept_through_a_resize(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_swap(drv)
                drv.execute_script("__wallsSwap.setSidebarWidth(380, true);")
                drv.execute_script("closeSwapModal(); openSwapModal();")
                time.sleep(1.0)
                drv.execute_script("__wallsSwap.setSidebarWidth(380, true);")
                time.sleep(0.3)
                dragged = drv.execute_script(self.DRAG)
                self.assertGreater(dragged, 450)
                drv.set_window_size(1580, 1000)
                time.sleep(0.6)
                drv.set_window_size(1600, 1000)
                time.sleep(0.6)
                self.assertAlmostEqual(
                    drv.execute_script(S + "getSidebarWidth()"), dragged, delta=2)


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class UntypedWallsAreNamedAndSelectable(_SwapPage):

    def test_no_type_and_deleted_type_are_told_apart_and_rows_select(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_swap(drv)
                rows = drv.execute_script(
                    "return [...document.querySelectorAll('#swapLegend"
                    " .swap-legend-row')].map(r => r.querySelector("
                    "'.swap-legend-name').textContent);")
                self.assertIn("(no wall type)", rows)
                self.assertIn("(deleted wall type)", rows)

                for name, seg in (("(no wall type)", "s5"),
                                  ("(deleted wall type)", "s6")):
                    drv.execute_script("clearSwapSelection();")
                    row = drv.execute_script(
                        "return [...document.querySelectorAll('#swapLegend"
                        " .swap-legend-row')].find(r => r.querySelector("
                        "'.swap-legend-name').textContent === arguments[0]);", name)
                    row.click()
                    time.sleep(0.2)
                    self.assertEqual(drv.execute_script(S + "getSelected()"), [seg])
                    groups = drv.execute_script(S + "getGroups()")
                    self.assertEqual([g["name"] for g in groups], [name])


if __name__ == "__main__":
    unittest.main()
