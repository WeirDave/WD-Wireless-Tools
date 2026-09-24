"""The drop-zone landing of every file-based tool fits a laptop screen.

Quick Walls, Prep, Capacity, PlanTrim, Report and AP Labeler share one
landing: logo, description, a dashed drop target, Open, and three steps. It
opened with 96px of padding and a 180px logo, so on a 1280x720 or 1366x768
screen the steps - and on Quick Walls the Open button - were below the fold.
The logo and spacing now scale with the window height.

The second test is the one that was nearly shipped broken: that top padding
is also what keeps the logo clear of `.dz-topbar`, which is fixed, and the
first version of the rule slid the logo underneath it. Measured in a real
browser because both are claims about where things land.
"""
from __future__ import annotations

import unittest

from tests import test_squirrel_home_fits_the_screen as harness

if harness.HAVE_SELENIUM:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

TOOLS = ["/walls", "/prep", "/capacity", "/plantrim", "/report", "/aprename"]

MEASURE = """
function shown(e) { return !!e && e.getBoundingClientRect().height > 0; }
var parts = Array.prototype.slice.call(document.querySelectorAll(
  '.dropzone-logo, .dropzone-brand-logo, .dropzone-cta, .dropzone-open-disk, .dropzone-steps'))
  .filter(shown);
var logo = document.querySelector('.dropzone-logo, .dropzone-brand-logo');
var bar = document.querySelector('.dz-topbar');
return {
  parts: parts.length,
  bottom: Math.max.apply(null, parts.map(function (e) { return e.getBoundingClientRect().bottom; })),
  logoTop: shown(logo) ? logo.getBoundingClientRect().top : null,
  barBottom: shown(bar) ? bar.getBoundingClientRect().bottom : 0,
  innerWidth: window.innerWidth,
  innerHeight: window.innerHeight
};
"""


@unittest.skipUnless(harness.HAVE_SELENIUM, "selenium is not installed")
class ToolLandingsFitTheScreenTests(harness.BrowserPagesHarness):

    def measure(self, drv, path, width, height):
        drv.set_window_size(width, height)
        drv.get(self.base + path)
        WebDriverWait(drv, 15).until(
            EC.visibility_of_element_located((By.CSS_SELECTOR, ".dropzone-cta")))
        return drv.execute_script(MEASURE)

    def test_the_steps_are_on_screen_on_a_laptop(self):
        for kind, drv in self.each_browser():
            for path in TOOLS:
                with self.subTest(browser=kind, tool=path):
                    m = self.measure(drv, path, 1366, 720)
                    if m["innerHeight"] < 640:
                        self.skipTest("%s gave a %dpx-tall viewport"
                                      % (kind, m["innerHeight"]))
                    self.assertGreaterEqual(m["parts"], 3, m)
                    self.assertLessEqual(m["bottom"], m["innerHeight"], m)

    def test_the_logo_is_never_under_the_fixed_top_bar(self):
        for kind, drv in self.each_browser():
            for path in TOOLS:
                for size in ((1366, 720), (1920, 1080)):
                    with self.subTest(browser=kind, tool=path, size=size):
                        m = self.measure(drv, path, *size)
                        self.assertIsNotNone(m["logoTop"], m)
                        self.assertGreaterEqual(m["logoTop"], m["barBottom"], m)


    def test_the_logo_scales_with_the_window_rather_than_stepping(self):
        """Adaptive, not one breakpoint: a taller window gets a bigger logo
        at every step, up to the full 180px on a tall screen."""
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                sizes = []
                for h in (720, 900, 1300):
                    self.measure(drv, "/walls", 1440, h)
                    sizes.append(drv.execute_script(
                        "return document.querySelector('.dropzone-logo')"
                        ".getBoundingClientRect().height;"))
                self.assertLess(sizes[0], sizes[1], sizes)
                self.assertLess(sizes[1], sizes[2], sizes)
                self.assertAlmostEqual(sizes[2], 180, delta=1)

if __name__ == "__main__":
    unittest.main()
