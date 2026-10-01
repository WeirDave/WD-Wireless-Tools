"""PlanTrim on a 43-storey building, and checking the corners before a cut.

"we are in a building ... that is 43 stories so that is a possibility" - one
full card per floor ran the rail off the screen. And "I need to be able to
make sure I can zoom in and examine the corners of this and make sure that
I'm not cutting away stuff that I might need later": each corner button
frames one corner of what will be kept.

Driven in a real browser with an invented 43-floor project.
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
    from selenium.webdriver.support.ui import WebDriverWait

FLOORS = 43
W, H = 1400, 2000


def _esx(path):
    from PIL import Image, ImageDraw
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    d.rectangle([150, 200, 1200, 1700], outline="black", width=5)
    b = io.BytesIO()
    im.save(b, "PNG")
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project.json", json.dumps(
            {"project": {"id": "proj-invented-43", "name": "Invented 43"}}))
        z.writestr("floorPlans.json", json.dumps({"floorPlans": [
            {"id": "f%d" % i, "name": "Level %d" % (i + 1), "imageId": "img",
             "width": W, "height": H, "metersPerUnit": 0.03}
            for i in range(FLOORS)]}))
        z.writestr("images.json", json.dumps({"images": [
            {"id": "img", "imageFormat": "PNG", "resolutionWidth": W,
             "resolutionHeight": H}]}))
        z.writestr("image-img", b.getvalue())
    return path


VIEW = """
var b = window.__plantrimBox, cv = document.getElementById('ptbCanvas');
return {scale: b.view.scale, x: b.view.x, y: b.view.y, cw: cv.width, ch: cv.height};
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class ATallBuildingInPlanTrim(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.esx = _esx(Path(cls._tmp.name) / "invented-43.esx")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._tmp.cleanup()

    def open(self, drv):
        drv.set_window_size(1366, 900)
        drv.get(self.base + "/plantrim")
        WebDriverWait(drv, 15).until(
            lambda d: d.find_elements(By.ID, "fileInput"))
        drv.find_element(By.ID, "fileInput").send_keys(str(self.esx))
        WebDriverWait(drv, 30).until(lambda d: d.execute_script(
            "var b = window.__plantrimBox; return !!(b && b.img && b.img.width);"))
        WebDriverWait(drv, 30).until(lambda d: len(d.find_elements(
            By.CSS_SELECTOR, "#ptbStrip .ptb-row")) == FLOORS)
        time.sleep(0.5)

    def test_the_floors_scroll_inside_the_rail(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open(drv)
                r = drv.execute_script("""
                  var s = document.getElementById('ptbStrip');
                  var foot = document.querySelector('.pb-rail .pb-rail-foot')
                    .getBoundingClientRect();
                  return {scrolls: s.scrollHeight > s.clientHeight,
                          footOnScreen: foot.bottom <= innerHeight};""")
                self.assertTrue(r["scrolls"], r)
                self.assertTrue(r["footOnScreen"], r)

    def test_each_corner_button_zooms_onto_that_corner(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open(drv)
                fit = drv.execute_script(VIEW)
                for corner, (fx, fy) in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
                    drv.find_element(By.CSS_SELECTOR,
                        '.ptb-corner-btns [data-arg-json="%d"]' % corner).click()
                    v = drv.execute_script(VIEW)
                    self.assertGreater(v["scale"], fit["scale"] * 3, v)
                    # The corner of what is kept is where the stage's centre is.
                    keep = drv.execute_script("""
                      var b = window.__plantrimBox;
                      return b.boxes[b.current] || null;""") or [0, 0, W, H]
                    cx = keep[2] if fx else keep[0]
                    cy = keep[3] if fy else keep[1]
                    sx = cx * v["scale"] + v["x"]
                    sy = cy * v["scale"] + v["y"]
                    self.assertAlmostEqual(sx, v["cw"] / 2, delta=2)
                    self.assertAlmostEqual(sy, v["ch"] / 2, delta=2)

    def test_the_way_to_draw_is_said_once(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open(drv)
                self.assertEqual(
                    drv.find_element(By.ID, "ptbHint").text.strip(), "")


if __name__ == "__main__":
    unittest.main()
