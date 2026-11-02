"""Choosing a section moves nothing but the settings inside the box.

"instead of making the stupid thing jump all over ... did you even test it in a
browser". The Settings window was one tall document: it scrolled with the
length of the open section, so the title left the top, a short section chosen
after a long one landed wherever the scroll had been, and the buttons changed
height on the two sections with nothing to save. Nothing on the page said which
section was open except the card.

Driven in real browsers, every section in turn:

* the cards, the box the settings sit in, its title bar and the buttons are in
  the same place and the same size for all nine;
* the page itself never scrolls;
* the title bar names the section whose card was pressed;
* the last setting in each section can be brought into view inside the box -
  Chrome and Edge wrap a <details>' content in an internal box that the first
  version of this layout never reached, so a long section was cut off with no
  way down to the rest.
"""
from __future__ import annotations

import time
import unittest

try:
    from selenium.webdriver.common.action_chains import ActionChains
except ImportError:                                  # HAVE_SELENIUM says so
    ActionChains = None
try:
    from selenium.webdriver.common.actions.wheel_input import ScrollOrigin
except ImportError:
    ScrollOrigin = None

from tests.test_squirrel_home_fits_the_screen import BrowserPagesHarness
from tests.test_strict_pages_work_in_a_browser import HAVE_SELENIUM

SECTIONS = ["general", "subfolders", "organizer", "cloud", "report",
            "walls", "capacity", "elsewhere", "backup"]

MEASURE = """
var r = function (e) {
  var b = e.getBoundingClientRect();
  return [Math.round(b.x), Math.round(b.y), Math.round(b.width), Math.round(b.height)];
};
var det = document.querySelector('details.s-section[open]');
var sum = det.querySelector('summary');
var se = document.scrollingElement;
return {
  nav: r(document.getElementById('sNav')),
  box: r(det),
  title: r(sum),
  titleText: sum.textContent.trim(),
  titleVisible: getComputedStyle(sum).position !== 'absolute' && sum.getBoundingClientRect().height > 20,
  foot: r(document.getElementById('sFooter')),
  pageScrolls: se.scrollHeight > se.clientHeight + 1,
  cardName: document.querySelector('.s-nav-item.is-current .s-nav-name').textContent.trim()
};"""

REACH = """
var det = document.querySelector('details.s-section[open]');
var body = det.querySelector('.s-body');
var last = body.lastElementChild;
while (last && last.getBoundingClientRect().height === 0 && last.previousElementSibling) {
  last = last.previousElementSibling;
}
var l = last.getBoundingClientRect(), b = det.getBoundingClientRect();
return {lastBottom: Math.round(l.bottom), boxBottom: Math.round(b.bottom),
        boxTop: Math.round(b.top), lastTop: Math.round(l.top)};"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class TheSettingsFrameHoldsStill(BrowserPagesHarness):
    def test_nothing_but_the_settings_moves_when_a_section_is_chosen(self):
        for kind, drv in self.each_browser():
            drv.set_window_size(1600, 900)
            drv.get(self.base + "/settings")
            time.sleep(1.5)
            first = None
            for sec in SECTIONS:
                with self.subTest(browser=kind, section=sec):
                    drv.execute_script(
                        "document.querySelector('.s-nav-item[data-sec=\"sec-%s\"]').click();" % sec)
                    time.sleep(0.4)
                    m = drv.execute_script(MEASURE)
                    self.assertFalse(m["pageScrolls"], "the page itself scrolls")
                    self.assertTrue(m["titleVisible"], "the section has no visible title")
                    self.assertEqual(m["titleText"], m["cardName"],
                                     "the title is not the card that was pressed")
                    if first is None:
                        first = m
                        continue
                    for part in ("nav", "box", "title", "foot"):
                        # A pixel is sub-pixel rounding of a fractional height,
                        # not movement.
                        for got, want in zip(m[part], first[part]):
                            self.assertLessEqual(abs(got - want), 1,
                                                 "%s moved between sections: %s against %s"
                                                 % (part, m[part], first[part]))

    def test_the_panel_has_no_empty_margins_either_side(self):
        """Settings opened as a panel over Home: the content fills it. The panel
        was widened to 1480px while the content stayed capped at 1200px, which
        left a blank gutter of well over a hundred pixels on both sides."""
        for kind, drv in self.each_browser():
            drv.set_window_size(1900, 1000)
            drv.get(self.base + "/")
            time.sleep(1.5)
            drv.execute_script("WD.openSettings();")
            time.sleep(2.5)
            m = drv.execute_script("""
              var f = document.querySelector('.wd-settings-frame');
              var d = f.contentDocument;
              var nav = d.getElementById('sNav').getBoundingClientRect();
              var main = d.querySelector('.s-main').getBoundingClientRect();
              var title = d.querySelector('.settings-title').getBoundingClientRect();
              return {frame: f.clientWidth, left: Math.round(nav.left),
                      right: Math.round(f.clientWidth - main.right),
                      titleLeft: Math.round(title.left)};""")
            with self.subTest(browser=kind):
                self.assertLessEqual(m["left"], 48, m)
                self.assertLessEqual(m["right"], 48, m)
                self.assertLessEqual(m["titleLeft"], 48, m)

    def test_the_last_setting_of_every_section_can_be_reached(self):
        for kind, drv in self.each_browser():
            drv.set_window_size(1600, 900)
            drv.get(self.base + "/settings")
            time.sleep(1.5)
            for sec in SECTIONS:
                with self.subTest(browser=kind, section=sec):
                    drv.execute_script(
                        "document.querySelector('.s-nav-item[data-sec=\"sec-%s\"]').click();" % sec)
                    time.sleep(0.4)
                    # With the mouse wheel, over the box, the way a person
                    # scrolls it. `scrollIntoView` was tried first and passed
                    # without the fix: script can scroll a box that has
                    # `overflow: hidden`, a person cannot.
                    box = drv.find_element("css selector", "details.s-section[open] > summary")
                    # `scroll_by_amount` scrolls from the window's corner, which is
                    # over the top bar, so the wheel is aimed at the box.
                    origin = ScrollOrigin.from_element(box, 60, 120)
                    for _ in range(6):
                        ActionChains(drv).scroll_from_origin(origin, 0, 1500).perform()
                    time.sleep(0.3)
                    r = drv.execute_script(REACH)
                    self.assertLessEqual(r["lastBottom"], r["boxBottom"] + 1,
                                         "the end of the section is cut off below its box: %s" % r)
                    # The last block can be taller than the box (a long "What is
                    # saved" list), so its top may sit above it; its end is what
                    # has to be inside.
                    self.assertGreaterEqual(r["lastBottom"], r["boxTop"], r)


if __name__ == "__main__":
    unittest.main()
