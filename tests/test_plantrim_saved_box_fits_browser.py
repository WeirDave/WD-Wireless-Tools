"""A saved keep-region is only put back on a sheet it fits, in a real browser.

Boxes are stored by the project's id, and a trimmed copy keeps that id. So
opening the output of an earlier trim laid the box drawn on the full-size
original over the smaller sheet: it landed off the drawing, the view framed it
and pushed the plan to the edge of the stage, the whole plan was shaded as
"thrown away", Reset view could not recover it, and the handles were off the
drawing where nothing could be grabbed. The floor card said only "your box is
still saved".

Driven through the real app with an invented project. What is asserted is what
he needs from the page: the plan is framed in the middle of the stage, no box
sits on it, the floor card says why, the store still holds the box for the
file it belongs to, and a rectangle can be drawn with the mouse.
"""
from __future__ import annotations

import io
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

PROJECT = "proj-invented-portrait"
SHEET = (1200, 1800)
#: Drawn on a 2400-wide original; this copy's sheet is 1200 wide.
TOO_BIG = [900, 300, 2300, 2100]
#: Fits this sheet.
FITS = [100, 150, 1100, 1650]


def _sheet_png():
    from PIL import Image, ImageDraw
    w, h = SHEET
    im = Image.new("RGB", (w, h), "white")
    d = ImageDraw.Draw(im)
    d.rectangle([60, 60, w - 60, h - 60], outline="black", width=6)
    for x in range(160, w - 60, 160):
        d.line([(x, 60), (x, h - 60)], fill="black", width=2)
    b = io.BytesIO()
    im.save(b, "PNG")
    return b.getvalue()


def _esx(path):
    w, h = SHEET
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("project.json", json.dumps(
            {"project": {"id": PROJECT, "name": "Invented Portrait"}}))
        z.writestr("floorPlans.json", json.dumps({"floorPlans": [
            {"id": "f1", "name": "01", "imageId": "img-f1", "width": w,
             "height": h, "metersPerUnit": 0.03}]}))
        z.writestr("images.json", json.dumps({"images": [
            {"id": "img-f1", "imageFormat": "PNG", "resolutionWidth": w,
             "resolutionHeight": h}]}))
        z.writestr("image-img-f1", _sheet_png())
    return path


STATE = """
var b = window.__plantrimBox;
var cv = document.getElementById('ptbCanvas');
var r = cv.getBoundingClientRect();
var k = cv.width / r.width;
var tl = {x: b.view.x / k + r.left, y: b.view.y / k + r.top};
var w = b.img ? b.img.width * b.view.scale / k : 0;
var h = b.img ? b.img.height * b.view.scale / k : 0;
var card = document.querySelector('.pb-rail .is-current, .pb-rail [aria-current]')
  || document.querySelector('.pb-rail');
return {box: b.boxes[b.current] || null,
        plan: [tl.x, tl.y, w, h], stage: [r.left, r.top, r.width, r.height],
        rail: document.querySelector('.pb-rail').textContent};
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class ASavedBoxGoesOnlyWhereItFits(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.esx = _esx(Path(cls._tmp.name) / "invented-portrait.esx")

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

    def open_with(self, drv, saved):
        self.api("boxes_save", {"projectId": PROJECT, "boxes": saved})
        drv.set_window_size(1600, 1000)
        drv.get(self.base + "/plantrim")
        WebDriverWait(drv, 15).until(
            lambda d: d.find_elements(By.ID, "fileInput"))
        drv.find_element(By.ID, "fileInput").send_keys(str(self.esx))
        WebDriverWait(drv, 30).until(lambda d: d.execute_script(
            "var b = window.__plantrimBox; return !!(b && b.img && b.img.width);"))
        time.sleep(1.0)
        return drv.execute_script(STATE)

    def assert_plan_is_framed(self, s):
        px, py, pw, ph = s["plan"]
        sx, sy, sw, sh = s["stage"]
        self.assertGreater(pw, sw * 0.2, s)
        # Centred: the gap either side of the plan is about the same.
        left, right = px - sx, (sx + sw) - (px + pw)
        self.assertLess(abs(left - right), sw * 0.1, s)
        self.assertGreaterEqual(px, sx - 1, s)
        self.assertLessEqual(px + pw, sx + sw + 1, s)

    def test_a_box_from_a_larger_sheet_is_set_aside(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                s = self.open_with(drv, {"f1": TOO_BIG})
                self.assertIsNone(s["box"], s)
                self.assert_plan_is_framed(s)
                self.assertIn("does not fit this one", s["rail"])
                kept = self.api("boxes_load", {"projectId": PROJECT})["boxes"]
                self.assertEqual(kept.get("f1"), [float(v) for v in TOO_BIG],
                                 "the box was lost for the file it belongs to")

    def test_a_box_that_fits_is_still_restored(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                s = self.open_with(drv, {"f1": FITS})
                self.assertEqual(s["box"], [float(v) for v in FITS], s)

    def test_a_rectangle_can_be_drawn_with_the_mouse(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                s = self.open_with(drv, {"f1": TOO_BIG})
                px, py, pw, ph = s["plan"]
                cv = drv.find_element(By.ID, "ptbCanvas")
                r = drv.execute_script(
                    "var r = arguments[0].getBoundingClientRect();"
                    "return [r.left, r.top, r.width, r.height];", cv)
                # From a quarter in to three quarters in, on the plan.
                x0 = px + pw * 0.25 - (r[0] + r[2] / 2)
                y0 = py + ph * 0.25 - (r[1] + r[3] / 2)
                (ActionChains(drv)
                 .move_to_element_with_offset(cv, int(x0), int(y0))
                 .click_and_hold()
                 .move_by_offset(int(pw * 0.25), int(ph * 0.25))
                 .move_by_offset(int(pw * 0.25), int(ph * 0.25))
                 .release().perform())
                time.sleep(0.3)
                b = drv.execute_script(STATE)["box"]
                self.assertIsNotNone(b, "dragging on the plan drew nothing")
                w, h = SHEET
                self.assertAlmostEqual(b[0], w * 0.25, delta=w * 0.05)
                self.assertAlmostEqual(b[2], w * 0.75, delta=w * 0.05)
                self.assertAlmostEqual(b[1], h * 0.25, delta=h * 0.05)
                self.assertAlmostEqual(b[3], h * 0.75, delta=h * 0.05)


if __name__ == "__main__":
    unittest.main()
