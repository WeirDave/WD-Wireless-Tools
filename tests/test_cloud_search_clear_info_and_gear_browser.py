"""Cloud Manager on a 1366x768 laptop: the search clear button, the matching
explanation and the settings gear.

* The × that empties the search box was an unstyled browser button around a
  default-size glyph. It is a 30px square now, and clicking it still empties
  the box.
* The ⓘ explanation was the default 440px modal - its own 640px maximum never
  applied - so it opened as a narrow strip that scrolled on every laptop. It is
  wide enough to read in columns, and its body does not scroll at 1366x768.
* The settings gear was the U+2699 character drawn in the disc's own
  background colour, which several platforms render as a speck. It is an SVG
  with real geometry, in a disc that keeps its 28px size.

The page is the real Cloud page with the real stylesheet. Signed out, the
toolbar is hidden, so the probe un-hides the ancestors of the controls it
measures; nothing else about the page is changed.
"""
from __future__ import annotations

import unittest

from tests.test_squirrel_home_fits_the_screen import BrowserPagesHarness
from tests.test_strict_pages_work_in_a_browser import HAVE_SELENIUM

if HAVE_SELENIUM:
    from selenium.webdriver.support.ui import WebDriverWait

SHOW_TOOLBAR = """
var e = document.querySelector('.clear-search');
while (e && e !== document.body) {
  if (getComputedStyle(e).display === 'none') e.style.display = 'block';
  e = e.parentElement;
}
"""

MEASURE = SHOW_TOOLBAR + """
var box = document.getElementById('searchBox');
box.value = 'invented';
var x = document.querySelector('.clear-search');
var xr = x.getBoundingClientRect();
x.click();
var gear = document.querySelector('.btn-icon-only[data-fn="openSettings"]');
var gr = gear.getBoundingClientRect();
var path = gear.querySelector('svg path');
var pb = path ? path.getBBox() : null;
showModal('matchHelpModal');
var m = document.querySelector('#matchHelpModal .modal');
var b = m.querySelector('.mh-body');
var mr = m.getBoundingClientRect();
return {
  xSize: [xr.width, xr.height], boxAfterClick: box.value,
  gearSize: [gr.width, gr.height], gearText: gear.textContent.trim(),
  gearBox: pb ? [pb.width, pb.height] : null,
  modalWidth: mr.width, bodyScroll: b.scrollHeight - b.clientHeight,
  modalScroll: m.scrollHeight - m.clientHeight, viewport: [innerWidth, innerHeight]
};
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class TheCloudToolbarAndHelpOnALaptop(BrowserPagesHarness):

    def measure(self, drv, theme):
        drv.set_window_size(1366, 768)
        drv.get(self.base + "/cloud")
        WebDriverWait(drv, 15).until(lambda d: d.execute_script(
            "return typeof showModal === 'function' && typeof clearSearch === 'function';"))
        drv.execute_script(
            "document.documentElement.setAttribute('data-theme', arguments[0]);", theme)
        return drv.execute_script(MEASURE)

    def test_the_clear_button_is_large_and_still_clears(self):
        for kind, drv in self.each_browser():
            for theme in ("dark", "light"):
                with self.subTest(browser=kind, theme=theme):
                    r = self.measure(drv, theme)
                    self.assertGreaterEqual(r["xSize"][0], 28, r)
                    self.assertGreaterEqual(r["xSize"][1], 28, r)
                    self.assertEqual(r["boxAfterClick"], "", r)

    def test_the_gear_is_drawn_and_keeps_its_size(self):
        for kind, drv in self.each_browser():
            for theme in ("dark", "light"):
                with self.subTest(browser=kind, theme=theme):
                    r = self.measure(drv, theme)
                    self.assertEqual(r["gearSize"], [28, 28], r)
                    self.assertEqual(r["gearText"], "", r)
                    self.assertGreater(r["gearBox"][0], 15, r)
                    self.assertGreater(r["gearBox"][1], 15, r)

    def test_the_matching_explanation_is_wide_and_does_not_scroll(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                r = self.measure(drv, "dark")
                self.assertGreaterEqual(r["modalWidth"], 900, r)
                self.assertLessEqual(r["bodyScroll"], 0, r)
                self.assertLessEqual(r["modalScroll"], 0, r)


if __name__ == "__main__":
    unittest.main()
