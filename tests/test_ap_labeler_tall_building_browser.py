"""AP Labeler on a sixty-floor building, and the pattern's example under it.

"what happens if we have 60 floors or 100 floors" - one full-width card per
floor ran the floors rail three screens tall, and "Choose floors" laid sixty
checkboxes one per line, pushing Numbering 1,800px down the panel. And "we
don't really need to see every single solitary access point we just need to
see what it's going to look like ... the example actually should be right
below ... the name pattern": the panel listed every AP, in a dock at the
bottom.

Driven in a real browser with an invented project of sixty floors.
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
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait

FLOORS = 60
PER_FLOOR = 6


def _esx(path):
    from PIL import Image
    im = Image.new("RGB", (1600, 1200), "white")
    b = io.BytesIO()
    im.save(b, "PNG")
    aps = [{"id": "a%d-%d" % (i, k), "name": "AP-%d-%d" % (i, k),
            "location": {"floorPlanId": "f%d" % i,
                         "coord": {"x": 200 + k * 200, "y": 400}}}
           for i in range(FLOORS) for k in range(PER_FLOOR)]
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project.json", json.dumps(
            {"project": {"id": "proj-invented-tall", "name": "Invented Tall"}}))
        z.writestr("floorPlans.json", json.dumps({"floorPlans": [
            {"id": "f%d" % i, "name": "%02d" % (i + 1), "imageId": "img",
             "width": 1600, "height": 1200, "metersPerUnit": 0.05}
            for i in range(FLOORS)]}))
        z.writestr("images.json", json.dumps({"images": [
            {"id": "img", "imageFormat": "PNG", "resolutionWidth": 1600,
             "resolutionHeight": 1200}]}))
        z.writestr("accessPoints.json", json.dumps({"accessPoints": aps}))
        z.writestr("image-img", b.getvalue())
    return path


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class ATallBuilding(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.esx = _esx(Path(cls._tmp.name) / "invented-tall.esx")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._tmp.cleanup()

    def open(self, drv, w=1366, h=900):
        drv.set_window_size(w, h)
        drv.get(self.base + "/aprename")
        WebDriverWait(drv, 15).until(
            lambda d: d.find_elements(By.ID, "fileInput"))
        drv.find_element(By.ID, "fileInput").send_keys(str(self.esx))
        WebDriverWait(drv, 30).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, "#arExampleBody tr"))
        time.sleep(0.5)

    def js(self, drv, script, *args):
        return drv.execute_script(script, *args)

    def test_the_floor_list_scrolls_inside_the_rail(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open(drv)
                r = self.js(drv, """
                  var t = document.getElementById('arFloorTabs');
                  var foot = document.querySelector('.ar-rail .pb-rail-foot')
                    .getBoundingClientRect();
                  return {tabs: t.querySelectorAll('.ar-floor-tab').length,
                          scrolls: t.scrollHeight > t.clientHeight,
                          footOnScreen: foot.bottom <= innerHeight};""")
                self.assertEqual(r["tabs"], FLOORS)
                self.assertTrue(r["scrolls"], r)
                self.assertTrue(r["footOnScreen"], r)

    def test_a_floor_far_down_the_list_stays_in_view_when_chosen(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open(drv)
                r = self.js(drv, """
                  var t = document.getElementById('arFloorTabs');
                  var tab = t.querySelector('[data-fp="f46"]');
                  tab.click();
                  var a = tab.getBoundingClientRect(), b = t.getBoundingClientRect();
                  return {active: tab.classList.contains('active'),
                          inView: a.top >= b.top - 1 && a.bottom <= b.bottom + 1};""")
                self.assertTrue(r["active"])
                self.assertTrue(r["inView"], r)

    def test_the_example_sits_under_the_pattern_and_is_short(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open(drv)
                r = self.js(drv, """
                  var sec = Array.prototype.map.call(
                    document.querySelectorAll('#arSideScroll > .ar-section'),
                    function (s) { return s.id || s.getAttribute('data-fold'); });
                  return {order: sec,
                          rows: document.querySelectorAll(
                            '#arExampleBody tr:not(.ar-example-gap)').length,
                          button: document.getElementById('arShowAllBtn').textContent};""")
                self.assertEqual(r["order"][:3], ["pattern", "arExampleSection", "floors"])
                self.assertLessEqual(r["rows"], 3)
                self.assertEqual(r["button"], "Show all %d names" % PER_FLOOR)

    def test_every_name_opens_in_its_own_window_and_closes(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open(drv)
                drv.find_element(By.ID, "arShowAllBtn").click()
                time.sleep(0.2)
                r = self.js(drv, """
                  var m = document.getElementById('arAllModal');
                  return {open: m.classList.contains('active')
                                && getComputedStyle(m).display !== 'none',
                          rows: document.querySelectorAll('#arPreviewBody tr').length};""")
                self.assertTrue(r["open"], r)
                self.assertEqual(r["rows"], PER_FLOOR)
                drv.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                time.sleep(0.2)
                self.assertFalse(self.js(drv,
                    "return document.getElementById('arAllModal')"
                    ".classList.contains('active');"))

    def test_choose_floors_does_not_push_the_rest_of_the_panel_away(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open(drv)
                drv.find_element(
                    By.CSS_SELECTOR, '#arFloorPickTabs [data-arg="chosen"]').click()
                time.sleep(0.2)
                r = self.js(drv, """
                  var rows = document.querySelector('#arFloorPickList .ar-fp-rows');
                  return {count: rows.querySelectorAll('.ar-fp-row').length,
                          height: rows.getBoundingClientRect().height,
                          scrolls: rows.scrollHeight > rows.clientHeight,
                          win: innerHeight};""")
                self.assertEqual(r["count"], FLOORS)
                self.assertTrue(r["scrolls"], r)
                self.assertLessEqual(r["height"], r["win"] * 0.4, r)


if __name__ == "__main__":
    unittest.main()
