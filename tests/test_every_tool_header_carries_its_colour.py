"""Every file-based tool's header bar is tinted with that tool's colour.

Quick Walls, Report and AP Labeler each carried their own header rules;
Prep, Capacity and PlanTrim never got any - PlanTrim's targeted `.topbar`,
a class its page does not use - so their bars were the plain default with a
white title while the drop box below them was coloured. Measured in a real
browser because the question is what is painted: whether the bar has a tint
and what colour the title comes out, in both themes, on the opening screen
bar and on the header shown once a file is open.
"""
from __future__ import annotations

import unittest

from tests import test_squirrel_home_fits_the_screen as harness

if harness.HAVE_SELENIUM:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

TOOLS = ["/walls", "/report", "/aprename", "/plantrim", "/prep", "/capacity"]

#: What the title is when no tool colour applies: white on the dark bar, the
#: body text colour on the light one.
UNCOLOURED = {"rgb(255, 255, 255)", "rgb(17, 24, 39)"}

MEASURE = """
document.documentElement.setAttribute('data-theme', arguments[0]);
var out = [];
['.dz-topbar', '.header'].forEach(function (sel) {
  var bar = document.querySelector(sel);
  if (!bar) return;
  var h1 = bar.querySelector('h1');
  out.push({
    bar: sel,
    tinted: getComputedStyle(bar).backgroundImage !== 'none',
    title: h1 ? getComputedStyle(h1).color : null
  });
});
return out;
"""


@unittest.skipUnless(harness.HAVE_SELENIUM, "selenium is not installed")
class EveryToolHeaderCarriesItsColourTests(harness.BrowserPagesHarness):

    def bars(self, drv, path, theme):
        drv.get(self.base + path)
        WebDriverWait(drv, 15).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, ".dz-topbar")))
        return drv.execute_script(MEASURE, theme)

    def test_every_header_is_tinted_and_its_title_coloured(self):
        for kind, drv in self.each_browser():
            for theme in ("dark", "light"):
                for path in TOOLS:
                    with self.subTest(browser=kind, theme=theme, tool=path):
                        bars = self.bars(drv, path, theme)
                        self.assertTrue(bars, "no header found")
                        for b in bars:
                            self.assertTrue(b["tinted"], b)
                            self.assertNotIn(b["title"], UNCOLOURED, b)

    def test_no_two_tools_share_a_title_colour(self):
        for kind, drv in self.each_browser():
            for theme in ("dark", "light"):
                with self.subTest(browser=kind, theme=theme):
                    seen = {}
                    for path in TOOLS:
                        seen[path] = self.bars(drv, path, theme)[0]["title"]
                    self.assertEqual(len(set(seen.values())), len(TOOLS), seen)


if __name__ == "__main__":
    unittest.main()
