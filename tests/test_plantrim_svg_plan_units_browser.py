"""A box drawn on a vector plan sized in points crops what was drawn.

An SVG floor plan written `width="612pt" height="396pt"` decodes in the browser
at 816 x 528 pixels (a point is 4/3 of a CSS pixel), while the plan the server
crops is 612 x 396 units - floorPlans.json's width and height. PlanTrim drew
the image at its own pixel size and read the pointer in those pixels, then
clamped the box to the plan's units and sent it: a box drawn over the middle
half of the sheet arrived as the lower right of it, and the crop kept a
different region from the one on screen.

Driven through the real app in a browser with an invented project. Where the
plan is on screen is measured from the canvas pixels - the sheet is solid red -
so the test does not trust the page's own view maths to say where it drew.
"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
import urllib.request
import zipfile
from pathlib import Path

from tests.test_squirrel_home_fits_the_screen import BrowserPagesHarness
from tests.test_strict_pages_work_in_a_browser import HAVE_SELENIUM

if HAVE_SELENIUM:
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

PROJECT = "proj-invented-points-sheet"
PLAN = (612, 396)
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="612pt" height="396pt" '
       'viewBox="0 0 612 396"><rect x="0" y="0" width="612" height="396" '
       'fill="#ff0000"/></svg>')


def _esx(path):
    w, h = PLAN
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project.json", json.dumps(
            {"project": {"id": PROJECT, "name": "Invented Points Sheet"}}))
        z.writestr("floorPlans.json", json.dumps({"floorPlans": [
            {"id": "f1", "name": "01", "imageId": "img-f1", "width": w,
             "height": h, "metersPerUnit": 0.03}]}))
        z.writestr("images.json", json.dumps({"images": [
            {"id": "img-f1", "imageFormat": "SVG", "resolutionWidth": w,
             "resolutionHeight": h}]}))
        z.writestr("image-img-f1", SVG)
    return path


#: The red sheet's extent on the canvas, in CSS pixels relative to the canvas.
RED_EXTENT = """
var cv = document.getElementById('ptbCanvas');
var g = cv.getContext('2d');
var d = g.getImageData(0, 0, cv.width, cv.height).data;
var x0 = Infinity, y0 = Infinity, x1 = -1, y1 = -1;
for (var y = 0; y < cv.height; y++) {
  for (var x = 0; x < cv.width; x++) {
    var i = (y * cv.width + x) * 4;
    if (d[i] > 120 && d[i + 1] < 60 && d[i + 2] < 60) {
      if (x < x0) x0 = x; if (x > x1) x1 = x;
      if (y < y0) y0 = y; if (y > y1) y1 = y;
    }
  }
}
var r = cv.getBoundingClientRect();
var k = cv.width / r.width;
return x1 < 0 ? null : [x0 / k, y0 / k, (x1 + 1) / k, (y1 + 1) / k, r.width, r.height];
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class ABoxOnAPointsSizedPlanCropsWhatWasDrawn(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.esx = _esx(Path(cls._tmp.name) / "invented-points-sheet.esx")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._tmp.cleanup()

    def api(self, action, payload):
        req = urllib.request.Request(
            self.base + "/api/plantrim/" + action,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json",
                     "X-WD-Wireless-Tools": "1"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))

    def test_the_box_sent_is_the_region_drawn(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                # A box saved by an earlier browser or run would be restored as
                # cropped, and dragging on a cropped floor draws nothing.
                self.api("boxes_save", {"projectId": PROJECT, "boxes": {}})
                drv.set_window_size(1600, 1000)
                drv.get(self.base + "/plantrim")
                WebDriverWait(drv, 15).until(
                    lambda d: d.find_elements(By.ID, "fileInput"))
                drv.find_element(By.ID, "fileInput").send_keys(str(self.esx))
                WebDriverWait(drv, 30).until(lambda d: d.execute_script(
                    "var b = window.__plantrimBox; return !!(b && b.img && b.img.width);"))
                WebDriverWait(drv, 30).until(lambda d: d.execute_script(
                    "return !!(window.__ptReport && window.__ptReport());"))
                time.sleep(0.5)
                # The browser really does size this sheet differently from the
                # plan, or the test is not testing anything.
                natural = drv.execute_script(
                    "var i = window.__plantrimBox.img; return [i.width, i.height];")
                self.assertNotEqual(natural, list(PLAN), natural)

                ext = drv.execute_script(RED_EXTENT)
                self.assertIsNotNone(ext, "the plan is not on the canvas")
                x0, y0, x1, y1, cw, ch = ext
                pw, ph = x1 - x0, y1 - y0
                cv = drv.find_element(By.ID, "ptbCanvas")
                # From a quarter in to three quarters in, on the plan as shown.
                sx = x0 + pw * 0.25 - cw / 2
                sy = y0 + ph * 0.25 - ch / 2
                (ActionChains(drv)
                 .move_to_element_with_offset(cv, int(round(sx)), int(round(sy)))
                 .click_and_hold()
                 .move_by_offset(int(round(pw * 0.25)), int(round(ph * 0.25)))
                 .move_by_offset(int(round(pw * 0.25)), int(round(ph * 0.25)))
                 .release().perform())
                time.sleep(0.3)
                drv.execute_script("window.ptbCropBox();")
                sent = drv.execute_script(
                    "var b = window.__ptBoxes(); return b && b.f1;")
                self.assertIsNotNone(sent, "nothing would be sent for the floor")
                w, h = PLAN
                want = [w * 0.25, h * 0.25, w * 0.75, h * 0.75]
                for got, exp, span in zip(sent, want, (w, h, w, h)):
                    self.assertAlmostEqual(got, exp, delta=span * 0.02,
                                           msg="sent %r, drew %r" % (sent, want))

                # And the server, working in plan units, crops to that size.
                def manual(d):
                    rep = d.execute_script("return window.__ptReport();")
                    fl = [f for f in (rep or {}).get("floors", []) if f["id"] == "f1"]
                    return fl[0] if fl and fl[0].get("source") == "manual" else None
                floor = WebDriverWait(drv, 30).until(manual)
                self.assertAlmostEqual(floor["newSize"][0], w * 0.5, delta=w * 0.03)
                self.assertAlmostEqual(floor["newSize"][1], h * 0.5, delta=h * 0.03)


if __name__ == "__main__":
    unittest.main()
