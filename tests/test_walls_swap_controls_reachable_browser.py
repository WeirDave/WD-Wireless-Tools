"""Visual Swap's controls can be reached with a big selection on a laptop.

On a 1366-wide window the Selected panel was squeezed to fit, and its own
`overflow: hidden` cut off "Change checked to", Swap and Delete selected with
no scroll bar to reach them. Only the list of walls shrinks and scrolls now,
and the sidebar scrolls when the window is shorter than all of it.

"Reachable" is measured, not inferred from the stylesheet: each control is
scrolled into view the way a person would scroll to it, and the element the
browser finds at its centre has to be that control - not a panel edge that
clips it, and not nothing.
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

CONTROLS = ["swapTargetType", "swapApplyBtn", "swapDeleteBtn",
            "swapFromType", "swapToType"]


def _esx(path):
    from PIL import Image
    w, h = 1600, 2400
    im = Image.new("RGB", (w, h), "white")
    b = io.BytesIO()
    im.save(b, "PNG")
    types = [("wt-a", "Wall, Invented A", "#C9A27A"),
             ("wt-b", "Door, Invented B", "#8B5A2B"),
             ("wt-c", "Window, Invented C", "#0093EA")]
    pts, segs = [], []
    n = 0
    for gx in range(100, w - 150, 90):
        for gy in range(100, h - 100, 110):
            a, z = "p%d" % len(pts), "p%d" % (len(pts) + 1)
            pts.append({"id": a, "location": {"floorPlanId": "f1",
                                              "coord": {"x": gx, "y": gy}}})
            pts.append({"id": z, "location": {"floorPlanId": "f1",
                                              "coord": {"x": gx + 80, "y": gy}}})
            segs.append({"id": "s%d" % n, "wallPoints": [a, z],
                         "wallTypeId": types[n % 3][0]})
            n += 1
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("project.json", json.dumps(
            {"project": {"id": "proj-invented-swap", "name": "Invented Swap"}}))
        zf.writestr("floorPlans.json", json.dumps({"floorPlans": [
            {"id": "f1", "name": "01", "imageId": "img-f1", "width": w,
             "height": h, "metersPerUnit": 0.03}]}))
        zf.writestr("images.json", json.dumps({"images": [
            {"id": "img-f1", "imageFormat": "PNG", "resolutionWidth": w,
             "resolutionHeight": h}]}))
        zf.writestr("wallTypes.json", json.dumps({"wallTypes": [
            {"id": i, "name": nm, "color": c, "thickness": 0.1,
             "attenuations": []} for i, nm, c in types]}))
        zf.writestr("wallPoints.json", json.dumps({"wallPoints": pts}))
        zf.writestr("wallSegments.json", json.dumps({"wallSegments": segs}))
        zf.writestr("image-img-f1", b.getvalue())
    return path


REACH = """
/* Scroll only what a person can scroll. `scrollIntoView` also scrolls an
   `overflow: hidden` box, which no mouse wheel or scroll bar can do, so it
   would find a clipped control "reachable". Clipping boxes are put back to
   the top and only auto/scroll boxes are moved. */
function userScrollable(el) {
  var o = getComputedStyle(el).overflowY;
  return o === 'auto' || o === 'scroll';
}
var out = {};
arguments[0].forEach(function (id) {
  var el = document.getElementById(id);
  if (!el) { out[id] = 'missing'; return; }
  var chain = [];
  for (var p = el.parentElement; p; p = p.parentElement) chain.push(p);
  chain.forEach(function (p) { if (!userScrollable(p)) p.scrollTop = 0; });
  chain.forEach(function (p) {
    if (!userScrollable(p)) return;
    var pr = p.getBoundingClientRect(), r = el.getBoundingClientRect();
    if (r.bottom > pr.bottom) p.scrollTop += r.bottom - pr.bottom + 8;
    r = el.getBoundingClientRect();
    if (r.top < pr.top) p.scrollTop -= pr.top - r.top + 8;
  });
  var r = el.getBoundingClientRect();
  var hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2);
  out[id] = (hit === el || el.contains(hit)) ? 'ok'
    : ('covered by ' + (hit ? (hit.id || hit.className || hit.tagName) : 'nothing')
       + ' at ' + Math.round(r.top) + '..' + Math.round(r.bottom)
       + ' of ' + innerHeight);
});
return out;
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class TheSwapControlsCanBeReached(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.esx = _esx(Path(cls._tmp.name) / "invented-swap.esx")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._tmp.cleanup()

    def open_swap(self, drv, width, height):
        drv.set_window_size(width, height)
        drv.get(self.base + "/walls")
        WebDriverWait(drv, 15).until(
            lambda d: d.find_elements(By.ID, "fileInput"))
        drv.find_element(By.ID, "fileInput").send_keys(str(self.esx))
        WebDriverWait(drv, 20).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, ".wall-card"))
        drv.execute_script("openSwapModal();")
        WebDriverWait(drv, 20).until(lambda d: d.execute_script(
            "return !!(window.__wallsSwap && window.__wallsSwap.getSegmentCount());"))
        time.sleep(0.5)

    def check(self, width, height):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind, size="%dx%d" % (width, height)):
                self.open_swap(drv, width, height)
                drv.execute_script(
                    "window.__wallsSwap.selectAll(); expandAllSwapGroups();")
                time.sleep(0.3)
                self.assertGreater(len(drv.execute_script(
                    "return window.__wallsSwap.getSelected();")), 200)
                got = drv.execute_script(REACH, CONTROLS)
                self.assertEqual(got, {c: "ok" for c in CONTROLS})

    def test_on_a_laptop(self):
        self.check(1366, 768)

    def test_on_a_large_monitor(self):
        self.check(2519, 1279)


if __name__ == "__main__":
    unittest.main()
