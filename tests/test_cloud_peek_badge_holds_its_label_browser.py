"""Cloud Manager's Peek badge holds its own label.

The badge gained the word "Peek" beside its eye, but stayed a 26px circle,
so the word spilled out over the folder's file counts next to it. It is a
pill on a wide window now, like the other labelled icon buttons, and a
circle with the label hidden below 1100px.

The badge is the real `previewBadge()` markup, on the real Cloud page with
the real stylesheet; the folder is invented.
"""
from __future__ import annotations

import unittest

from tests.test_squirrel_home_fits_the_screen import BrowserPagesHarness
from tests.test_strict_pages_work_in_a_browser import HAVE_SELENIUM

if HAVE_SELENIUM:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

PLACE = """
var html = previewBadge({path: 'C:/Invented/Site A/Invented.esx',
  src: {total: 3, esx: 1, srcCount: 2, plans: 2, images: 0, other: 0, srcSizeH: '4 MB'}});
var box = document.createElement('div');
box.id = 'peekProbe';
box.style.cssText = 'position:fixed;left:40px;top:200px;display:flex;gap:6px;align-items:center;z-index:99999';
box.innerHTML = html + '<span id="peekNext">3 files</span>';
document.body.appendChild(box);
var b = box.querySelector('.src-badge'), l = b.querySelector('.ib-label');
var br = b.getBoundingClientRect(), lr = l.getBoundingClientRect(),
    nr = document.getElementById('peekNext').getBoundingClientRect();
return {b: [br.left, br.right], l: [lr.left, lr.right], next: nr.left,
        shown: getComputedStyle(l).display !== 'none'};
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class ThePeekBadge(BrowserPagesHarness):

    def measure(self, drv, w):
        drv.set_window_size(w, 900)
        drv.get(self.base + "/cloud")
        WebDriverWait(drv, 15).until(lambda d: d.execute_script(
            "return typeof previewBadge === 'function';"))
        return drv.execute_script(PLACE)

    def test_the_label_sits_inside_the_badge_on_a_wide_window(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                r = self.measure(drv, 1600)
                self.assertTrue(r["shown"], r)
                self.assertLessEqual(r["l"][1], r["b"][1] + 0.5, r)
                self.assertLessEqual(r["b"][1], r["next"] + 0.5, r)

    def test_a_narrow_window_keeps_the_circle_without_the_word(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                r = self.measure(drv, 1000)
                self.assertFalse(r["shown"], r)
                self.assertAlmostEqual(r["b"][1] - r["b"][0], 26, delta=1)


if __name__ == "__main__":
    unittest.main()
