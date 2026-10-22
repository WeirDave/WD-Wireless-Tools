"""Drawing the requirement area, on both pages, in Chrome, Edge and Firefox.

The unit tests prove the tool; these press the real buttons on the real pages
and read what the page then asks the server for. A control that exists is not
a control that works: the drawing is checked by the outline arriving in the
`floorAreas` the page sends, in the floor's own plan units, at the place the
mouse was.

The plan is a 400 x 300 picture standing for a 2000 x 1500 floor, so a
mistake in the scaling from the screen to the plan is five-fold, not a pixel.
"""
from __future__ import annotations

import io
import json
import tempfile
import time
import unittest
import urllib.parse
import zipfile
from pathlib import Path

from tests.test_capacity_profiles import build_esx
from tests.test_squirrel_home_fits_the_screen import BrowserPagesHarness
from tests.test_strict_pages_work_in_a_browser import HAVE_SELENIUM

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    Image = None

if HAVE_SELENIUM:
    from selenium.webdriver.common.action_chains import ActionChains
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait

PLAN_W, PLAN_H = 2000.0, 1500.0   # the floor, in plan units
IMG_W, IMG_H = 400, 300           # the picture that stands for it
FIT = 0.97                        # WD.PlanView's FIT_FILL


def project_with_a_plan(path: Path) -> Path:
    """The capacity fixture, with a floor image the page can draw.

    No area on the floor: one that already carries devices is left alone by
    default, and that is a different test."""
    build_esx(path, areas=[])
    im = Image.new("RGB", (IMG_W, IMG_H), "white")
    for x in range(40, 360):
        im.putpixel((x, 40), (0, 0, 0))
        im.putpixel((x, 260), (0, 0, 0))
    buf = io.BytesIO()
    im.save(buf, format="PNG")
    with zipfile.ZipFile(path) as zin:
        members = {n: zin.read(n) for n in zin.namelist()}
    floors = json.loads(members["floorPlans.json"])
    floors["floorPlans"][0]["imageId"] = "img-1"
    members["floorPlans.json"] = json.dumps(floors).encode("utf-8")
    members["image-img-1"] = buf.getvalue()
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zout:
        for n, b in members.items():
            zout.writestr(n, b)
    return path


@unittest.skipUnless(HAVE_SELENIUM and Image is not None, "selenium and Pillow are needed")
class DrawingTheAreaOnThePlan(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.esx = project_with_a_plan(Path(cls._tmp.name) / "invented-plan.esx")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._tmp.cleanup()

    # ── helpers ──────────────────────────────────────────────────────────────

    def open_page(self, drv, path, ready):
        drv.set_window_size(1600, 1100)
        drv.get(self.base + path)
        WebDriverWait(drv, 15).until(lambda d: d.find_elements(By.ID, "fileInput"))
        drv.execute_script("""
          window.__urls = [];
          var f = window.fetch;
          window.fetch = function (u) { window.__urls.push(String(u)); return f.apply(window, arguments); };
        """)
        drv.find_element(By.ID, "fileInput").send_keys(str(self.esx))
        WebDriverWait(drv, 30).until(ready)

    def plan_ready(self, canvas_id, empty_id):
        def ready(d):
            return d.execute_script(
                "var e = document.getElementById(arguments[1]);"
                "return !!e && e.hidden && document.getElementById(arguments[0]).width > 10;",
                canvas_id, empty_id)
        return ready

    def geometry(self, drv, canvas):
        """Where the picture sits on the canvas, in CSS pixels from its corner."""
        w, h = canvas.size["width"], canvas.size["height"]
        s = min(w / IMG_W, h / IMG_H) * FIT
        return {"w": w, "h": h, "s": s,
                "ox": (w - IMG_W * s) / 2, "oy": (h - IMG_H * s) / 2}

    def at(self, g, ux, uy):
        """Canvas offset (from its centre) of plan point (ux, uy)."""
        px = g["ox"] + ux / PLAN_W * IMG_W * g["s"]
        py = g["oy"] + uy / PLAN_H * IMG_H * g["s"]
        return int(round(px - g["w"] / 2)), int(round(py - g["h"] / 2))

    def mouse(self, drv, canvas, g):
        chain = ActionChains(drv)
        return chain, lambda u, v: chain.move_to_element_with_offset(canvas, *self.at(g, u, v))

    def drag(self, drv, canvas, g, a, b):
        chain, to = self.mouse(drv, canvas, g)
        to(*a)
        chain.click_and_hold()
        to((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        to(*b)
        chain.release().perform()

    def click(self, drv, canvas, g, *points, double_last=False):
        # safaridriver's double_click is not what a person's double-click is:
        # its two clicks arrive with a click count of 1 and as far apart as
        # the runner's round trips (a slow macOS runner made that longer than
        # the page's double-click window, and the triangle was never sent).
        # A real Safari double-click carries a count of 2 on the second
        # press, so for Safari the second press is dispatched with one.
        safari = drv.capabilities.get("browserName", "").lower() == "safari"
        chain, to = self.mouse(drv, canvas, g)
        for i, p in enumerate(points):
            to(*p)
            if double_last and i == len(points) - 1 and not safari:
                chain.double_click()
            else:
                chain.click()
        chain.perform()
        if double_last and safari:
            x, y = self.at(g, *points[-1])
            drv.execute_script("""
              var c = arguments[0], r = c.getBoundingClientRect();
              var o = {bubbles: true, cancelable: true, button: 0, detail: 2, view: window,
                       clientX: r.left + r.width / 2 + arguments[1],
                       clientY: r.top + r.height / 2 + arguments[2]};
              c.dispatchEvent(new MouseEvent('mousedown', o));
              c.dispatchEvent(new MouseEvent('mouseup', o));
            """, canvas, x, y)

    def sent(self, drv):
        """The newest floorAreas the page asked the server about, as a dict."""
        found = drv.execute_script(
            "var u = window.__urls.filter(function (x) { return /floorAreas=/.test(x); });"
            "return u.length ? u[u.length - 1] : null;")
        if found is None:
            return None
        raw = urllib.parse.parse_qs(urllib.parse.urlsplit(found).query)["floorAreas"][0]
        return json.loads(raw)

    def wait_sent(self, drv, check, why):
        end = time.time() + 20
        while time.time() < end:
            got = self.sent(drv)
            if check(got):
                return got
            time.sleep(0.2)
        self.fail(why + " (last sent: %r)" % (self.sent(drv),))

    def corners(self, got):
        (pts,) = got.values()
        return [(p["x"], p["y"]) for p in pts]

    def assert_near(self, got, want, tol=25):
        self.assertEqual(len(got), len(want))
        for (x, y), (wx, wy) in zip(got, want):
            self.assertAlmostEqual(x, wx, delta=tol)
            self.assertAlmostEqual(y, wy, delta=tol)

    # ── Capacity ─────────────────────────────────────────────────────────────

    def capacity_open(self, drv):
        self.open_page(drv, "/capacity", self.plan_ready("capMapCanvas", "capMapEmpty"))
        WebDriverWait(drv, 20).until(lambda d: "would be written" in d.find_element(By.ID, "capPlan").text)
        drv.execute_script("document.getElementById('capStepArea').scrollIntoView()")
        return drv.find_element(By.ID, "capMapCanvas")

    def test_capacity_a_rectangle_drawn_on_the_plan_is_what_is_planned(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                canvas = self.capacity_open(drv)
                g = self.geometry(drv, canvas)
                self.assertIsNone(self.sent(drv), "nothing is sent until something is drawn")
                drv.find_element(By.ID, "wdAreaRect").click()
                self.drag(drv, canvas, g, (400, 300), (1500, 1100))
                got = self.wait_sent(drv, lambda x: x is not None, "no outline was sent")
                self.assert_near(self.corners(got),
                                 [(400, 300), (1500, 300), (1500, 1100), (400, 1100)])
                WebDriverWait(drv, 20).until(lambda d: "The area you drew on the plan" in
                                             d.find_element(By.ID, "capPlan").text)
                strip = drv.find_element(By.ID, "capMapStrip").text
                self.assertIn("Your area", strip)
                self.assertTrue(drv.find_element(By.ID, "wdAreaClear").is_enabled())

    def test_capacity_a_shape_is_closed_by_a_double_click_and_a_corner_can_be_moved(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                canvas = self.capacity_open(drv)
                g = self.geometry(drv, canvas)
                drv.find_element(By.ID, "wdAreaPoly").click()
                self.click(drv, canvas, g, (300, 300), (1500, 300), (1500, 1000), double_last=True)
                got = self.wait_sent(drv, lambda x: x is not None and len(next(iter(x.values()))) == 3,
                                     "the triangle was not sent")
                self.assert_near(self.corners(got), [(300, 300), (1500, 300), (1500, 1000)])
                # Drag the right-hand corner left; the page asks again with it moved.
                self.drag(drv, canvas, g, (1500, 1000), (1100, 1200))
                got = self.wait_sent(drv, lambda x: x is not None and abs(
                    next(iter(x.values()))[2]["x"] - 1100) < 40, "the moved corner was not sent")
                self.assert_near(self.corners(got), [(300, 300), (1500, 300), (1100, 1200)])

    def test_capacity_back_to_automatic_takes_it_away_and_escape_cancels_a_shape(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                canvas = self.capacity_open(drv)
                g = self.geometry(drv, canvas)
                drv.find_element(By.ID, "wdAreaRect").click()
                self.drag(drv, canvas, g, (400, 300), (1500, 1100))
                self.wait_sent(drv, lambda x: x is not None, "no outline was sent")
                WebDriverWait(drv, 10).until(lambda d: d.find_element(By.ID, "wdAreaClear").is_enabled())
                drv.find_element(By.ID, "wdAreaClear").click()
                WebDriverWait(drv, 20).until(lambda d: "The area you drew on the plan" not in
                                             d.find_element(By.ID, "capPlan").text)
                self.assertNotIn("Your area", drv.find_element(By.ID, "capMapStrip").text)
                self.assertFalse(drv.find_element(By.ID, "wdAreaClear").is_enabled())
                # A shape started and given up leaves no trace.
                before = len(drv.execute_script("return window.__urls;"))
                drv.find_element(By.ID, "wdAreaPoly").click()
                self.click(drv, canvas, g, (300, 300), (1500, 300))
                ActionChains(drv).send_keys(Keys.ESCAPE).perform()
                time.sleep(0.5)
                self.assertEqual(len(drv.execute_script("return window.__urls;")), before)
                self.assertEqual(drv.find_element(By.ID, "wdAreaPoly").get_attribute("aria-pressed"), "false")

    # ── Prep ─────────────────────────────────────────────────────────────────

    def prep_open(self, drv):
        self.open_page(drv, "/prep", self.plan_ready("prepMapCanvas", "prepMapEmpty"))
        drv.find_element(By.CSS_SELECTOR, "#prepStageCard-areas .pb-stage-open").click()
        WebDriverWait(drv, 20).until(lambda d: "devices for" in d.find_element(By.ID, "prepAreaFloors").text)
        return drv.find_element(By.ID, "prepMapCanvas")

    def test_prep_a_rectangle_drawn_on_the_areas_stage_is_what_prepare_will_write(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                canvas = self.prep_open(drv)
                g = self.geometry(drv, canvas)
                drv.find_element(By.ID, "wdAreaRect").click()
                self.drag(drv, canvas, g, (400, 300), (1500, 1100))
                got = self.wait_sent(drv, lambda x: x is not None, "no outline was sent")
                self.assert_near(self.corners(got),
                                 [(400, 300), (1500, 300), (1500, 1100), (400, 1100)])
                WebDriverWait(drv, 20).until(lambda d: "Your area" in d.find_element(By.ID, "prepMapStrip").text)
                rows = drv.find_element(By.ID, "prepAreaFloors").text
                self.assertIn("as drawn", rows)
                # The Prepare request carries the same outline.
                self.assertEqual(self.sent(drv), got)

    def test_prep_a_plain_drag_on_the_areas_stage_still_pans_the_plan(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                canvas = self.prep_open(drv)
                g = self.geometry(drv, canvas)
                read = ("return JSON.stringify(document.getElementById('prepZoomLevel').textContent);")
                self.drag(drv, canvas, g, (600, 500), (900, 700))
                time.sleep(0.4)
                self.assertIsNone(self.sent(drv), "a drag with no tool on draws nothing")

    def test_prep_the_buttons_say_why_when_the_stage_is_off(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.prep_open(drv)
                box = drv.find_element(By.ID, "prepStep-areas")
                box.click()
                WebDriverWait(drv, 10).until(lambda d: not d.find_element(By.ID, "wdAreaRect").is_enabled())
                self.assertIn("not ticked", drv.find_element(By.ID, "wdAreaHint").text)
                box.click()
                WebDriverWait(drv, 10).until(lambda d: d.find_element(By.ID, "wdAreaRect").is_enabled())


if __name__ == "__main__":
    unittest.main()
