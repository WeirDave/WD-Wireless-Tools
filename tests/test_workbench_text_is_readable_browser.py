"""Nothing a person reads in the workbench tools is set below 13px.

"I want the font to be large enough for a 60 year old person like myself
wearing readers can see the fucking thing". Before the readable-type block in
`wd-tools.css`, the five workbench tools set explanations at 11-12px and
badges at 9-10px, and he runs the browser at 90%.

Measured, not read off the stylesheet: each tool is opened in a real browser
with an invented project, every visible text node is walked, and its computed
size is checked. The shared page header is left out - it is the same on every
page, including the ones this block does not cover.
"""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from tests.esx_factory import make_esx
from tests.test_capacity_profiles import build_esx as capacity_esx
from tests.test_plantrim_saved_box_fits_browser import _esx as plan_esx
from tests.test_squirrel_home_fits_the_screen import BrowserPagesHarness
from tests.test_strict_pages_work_in_a_browser import HAVE_SELENIUM
from tests.test_walls_swap_controls_reachable_browser import _esx as walls_esx

if HAVE_SELENIUM:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

FLOOR_PX = 13

SMALL = """
var out = {};
var w = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
var n;
while ((n = w.nextNode())) {
  if (!n.textContent.trim()) continue;
  var el = n.parentElement;
  if (!el || el.closest('.header, .dz-topbar, .main-menu, .wd-menu, #wdDevRoot, .toasts, #toast, .dropzone'))
    continue;
  var r = el.getBoundingClientRect();
  if (!r.width || !r.height) continue;
  var cs = getComputedStyle(el);
  if (cs.visibility === 'hidden' || cs.display === 'none') continue;
  var fs = parseFloat(cs.fontSize);
  if (fs >= arguments[0]) continue;
  var key = el.tagName.toLowerCase()
    + (typeof el.className === 'string' && el.className.trim()
       ? '.' + el.className.trim().split(/\\s+/).join('.') : '')
    + ' ' + fs + 'px: ' + n.textContent.trim().slice(0, 30);
  out[key] = true;
}
return Object.keys(out).sort();
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class TheWorkbenchToolsAreReadable(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        d = Path(cls._tmp.name)
        cls.capacity = d / "invented-capacity.esx"
        capacity_esx(cls.capacity)
        cls.plan = plan_esx(d / "invented-plan.esx")
        cls.walls = walls_esx(d / "invented-walls.esx")
        cls.aps = make_esx(d / "invented-aps.esx", floors=2, aps=8, placed=True)
        #: A long name, the shape real project files have: site, building,
        #: street address, floors, design stage. Invented throughout.
        import shutil
        cls.long_names = {}
        for key, src in (("capacity", cls.capacity), ("plan", cls.plan),
                         ("walls", cls.walls), ("aps", cls.aps)):
            dst = d / ("Invented Campus - Building 12 - 1234 Example Street, "
                       "Exampletown - Floors 1 to 9 - Predictive %s.esx" % key)
            shutil.copy(src, dst)
            cls.long_names[key] = dst

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._tmp.cleanup()

    def small_text(self, drv, path, esx, ready):
        drv.set_window_size(2519, 1279)
        drv.get(self.base + path)
        WebDriverWait(drv, 15).until(
            lambda d: d.find_elements(By.ID, "fileInput"))
        drv.find_element(By.ID, "fileInput").send_keys(str(esx))
        WebDriverWait(drv, 30).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, ready))
        time.sleep(1.0)
        return drv.execute_script(SMALL, FLOOR_PX)

    def check(self, path, esx, ready):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind, page=path):
                self.assertEqual(self.small_text(drv, path, esx, ready), [])

    def test_capacity(self):
        self.check("/capacity", self.capacity, "#capTemplates .cap-tpl")

    def test_plantrim(self):
        self.check("/plantrim", self.plan, ".pb-rail .ptb-row")

    def test_prep(self):
        self.check("/prep", self.plan, ".pb-rail .pb-stage")

    def test_quick_walls(self):
        self.check("/walls", self.walls, ".wall-card")

    def test_ap_labeler(self):
        self.check("/aprename", self.aps, "#arPreview td")


    # -- the open file's name and the tool's title ----------------------------

    OVERLAP = """
      var b = document.getElementById('fileBadge').getBoundingClientRect();
      var t = Array.prototype.map.call(
          document.querySelectorAll('.header-center h1'),
          function (e) { return e.getBoundingClientRect(); })
        .filter(function (r) { return r.width > 0; })[0];
      return {badgeRight: b.right, titleLeft: t ? t.left : null};
    """

    def check_title_clear(self, path, key, ready):
        """Split screen on his monitor: a long project name ran underneath
        the centred title."""
        for kind, drv in self.each_browser():
            for width in (1280, 1100):
                with self.subTest(browser=kind, page=path, width=width):
                    drv.set_window_size(width, 900)
                    drv.get(self.base + path)
                    WebDriverWait(drv, 15).until(
                        lambda d: d.find_elements(By.ID, "fileInput"))
                    drv.find_element(By.ID, "fileInput").send_keys(
                        str(self.long_names[key]))
                    WebDriverWait(drv, 30).until(
                        lambda d: d.find_elements(By.CSS_SELECTOR, ready))
                    r = drv.execute_script(self.OVERLAP)
                    self.assertIsNotNone(r["titleLeft"], r)
                    self.assertLessEqual(r["badgeRight"], r["titleLeft"], r)

    def test_capacity_title_is_clear(self):
        self.check_title_clear("/capacity", "capacity", "#capTemplates .cap-tpl")

    def test_plantrim_title_is_clear(self):
        self.check_title_clear("/plantrim", "plan", ".pb-rail .ptb-row")

    def test_quick_walls_title_is_clear(self):
        self.check_title_clear("/walls", "walls", ".wall-card")

    def test_ap_labeler_title_is_clear(self):
        self.check_title_clear("/aprename", "aps", "#arPreview td")


if __name__ == "__main__":
    unittest.main()
