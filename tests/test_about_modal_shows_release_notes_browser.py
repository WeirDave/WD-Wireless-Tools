"""The About window, with an update available, on a 1366x768 laptop.

It was a 480px strip, and the list of what changed in the newer releases was
capped at 220px inside it - a few lines of a long note at a time. The window is
now wide, in two columns (this install on the left, the update and its notes on
the right), and the notes list is tall enough to read.

The probe opens the real About window on the real page, waits for its own
update check to finish, and mounts the real updater panel with invented
releases (the notes are long enough that the list must scroll, so its height
is the cap and not the content). Below 760px the layout must fall back to one
column in the old order: update first, then diagnostics.
"""
from __future__ import annotations

import unittest

from tests.test_squirrel_home_fits_the_screen import BrowserPagesHarness
from tests.test_strict_pages_work_in_a_browser import HAVE_SELENIUM

if HAVE_SELENIUM:
    from selenium.webdriver.support.ui import WebDriverWait

PREPARE = """
window.wdOpenAbout();
return true;
"""

IDLE = """
var b = document.querySelector('#wdAboutModal .wd-about-checkBtn');
return !!b && !b.disabled;
"""

MOUNT = """
var notes = [];
for (var i = 0; i < 14; i++) notes.push('- An invented line of release notes, number ' + i + ', long enough to read.');
var changes = [];
for (var v = 9; v >= 5; v--) {
  changes.push({ version: '9.0.' + v, title: 'Invented release ' + v,
                 notes: '## What changed\\n' + notes.join('\\n'), url: '' });
}
var panel = document.querySelector('#wdAboutModal .wd-update-panel');
WD.Updater.mount(panel, { localVersion: '9.0.0', latestVersion: '9.0.9',
                          latestUrl: '', changes: changes, changesTruncated: false });
return true;
"""

READY = """
var l = document.querySelector('#wdAboutModal .wd-update-panel .rc-list');
return !!l && l.querySelectorAll('.rc-item').length > 0;
"""

MEASURE = """
var q = function (s) { return document.querySelector('#wdAboutModal ' + s); };
var r = function (e) { var b = e.getBoundingClientRect();
  return { l: b.left, r: b.right, t: b.top, b: b.bottom, w: b.width, h: b.height }; };
var items = document.querySelectorAll('#wdAboutModal .rc-item');
if (items.length) items[0].open = true;
var modal = q('.wd-about-modal');
var list = q('.wd-update-panel .rc-list');
return {
  modal: r(modal), hero: r(q('.wd-about-hero')), update: r(q('.wd-about-update')),
  diag: r(q('.wd-about-diagnostics')), links: r(q('.wd-about-linkList')),
  list: r(list), modalScroll: modal.scrollHeight - modal.clientHeight,
  listScrolls: list.scrollHeight > list.clientHeight, viewport: [innerWidth, innerHeight]
};
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class TheAboutWindowShowsReleaseNotes(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        # The harness reports a "manual" install, whose panel has no update
        # button and no list of changes. A ZIP install is the ordinary case
        # that has both.
        import server
        server.updater.detect_install.return_value = {
            "method": "zip", "isGitInstall": False, "isDevCheckout": False,
            "currentVersion": "9.0.0", "reason": "Invented install."}

    def measure(self, drv, width, height):
        drv.set_window_size(width, height)
        drv.get(self.base + "/cloud")
        WebDriverWait(drv, 15).until(lambda d: d.execute_script(
            "return typeof window.wdOpenAbout === 'function' && !!window.WD && !!WD.Updater;"))
        drv.execute_script(PREPARE)
        WebDriverWait(drv, 15).until(lambda d: d.execute_script(IDLE))
        drv.execute_script(MOUNT)
        WebDriverWait(drv, 15).until(lambda d: d.execute_script(READY))
        return drv.execute_script(MEASURE)

    def test_it_is_wide_and_the_notes_list_is_tall(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                m = self.measure(drv, 1366, 768)
                self.assertGreaterEqual(m["modal"]["w"], 1000, m)
                self.assertGreaterEqual(m["list"]["w"], 500, m)
                # 185px was the list at this height before the window grew.
                self.assertGreaterEqual(m["list"]["h"], 220, m)
                self.assertTrue(m["listScrolls"], "the probe's notes must overflow the cap: " + str(m))
                self.assertLessEqual(m["modalScroll"], 0, m)
                self.assertLessEqual(m["modal"]["b"], m["viewport"][1], m)

    def test_this_install_sits_beside_the_update_and_is_not_spread_out(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                m = self.measure(drv, 1366, 768)
                self.assertGreaterEqual(m["update"]["l"], m["hero"]["r"], m)
                self.assertGreaterEqual(m["update"]["l"], m["diag"]["r"], m)
                # The notes are far taller than the left column; its sections
                # must stay together rather than share out the extra height.
                self.assertLess(m["diag"]["t"] - m["hero"]["b"], 40, m)
                self.assertLess(m["links"]["t"] - m["diag"]["b"], 40, m)

    def test_a_narrow_window_is_one_column_with_the_update_first(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                m = self.measure(drv, 700, 900)
                self.assertLess(m["update"]["t"], m["diag"]["t"], m)
                self.assertLessEqual(m["update"]["r"], m["modal"]["r"], m)
                self.assertGreaterEqual(m["update"]["w"], m["modal"]["w"] - 60, m)


if __name__ == "__main__":
    unittest.main()
