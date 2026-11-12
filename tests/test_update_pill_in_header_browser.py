"""The "an update is waiting" notice is a pill in the page header.

It was a full-width bar across the top of every page that pushed the page down
and had to be dismissed, with a second badge pinned to the bottom corner. It is
now one small pill beside the theme toggle; clicking it opens About, where the
Updates card turns amber and carries the notes and the update button.

The probe loads real pages from the real server (the update check is answered
by a stubbed updater that reports invented versions), waits for the page's own
check to draw the pill, then measures it and clicks it with a real mouse click.
Nothing here asserts that the source contains something: the pill has to be
visible, beside the toggle, and take no room from the page, and the click has to
open the window.
"""
from __future__ import annotations

import unittest
from unittest import mock

from tests.test_squirrel_home_fits_the_screen import BrowserPagesHarness
from tests.test_strict_pages_work_in_a_browser import HAVE_SELENIUM

if HAVE_SELENIUM:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

# Cloud Manager keeps its header on a screen that only exists once someone is
# signed in to Ekahau Cloud, which a test cannot be; it is shown here the way
# the page itself shows it (goToDashboard), and the pill must already be in it.
PAGES = ("/", "/cloud", "/report", "/scale", "/settings")
SHOW_CLOUD_HEADER = """
document.getElementById('loginScreen').style.display = 'none';
document.getElementById('appScreen').style.display = 'flex';
"""
CACHE_KEY = "wd-update-check"

INSTALL = {"method": "git", "isGitInstall": False, "isDevCheckout": False,
           "currentVersion": "9.0.0", "reason": "Invented install."}
NEWER = {"tag": "v9.0.9", "version": "9.0.9", "url": "https://example.invalid/r",
         "notes": "- An invented line."}
CURRENT = {"tag": "v9.0.0", "version": "9.0.0", "url": "https://example.invalid/r",
           "notes": ""}

# Visible pills only: a page with a drop screen and a workspace keeps two
# headers, and the hidden one carries a hidden pill.
MEASURE = """
var r = function (e) { var b = e.getBoundingClientRect();
  return { l: b.left, r: b.right, t: b.top, b: b.bottom, w: b.width, h: b.height }; };
var shown = Array.prototype.filter.call(document.querySelectorAll('.wd-update-pill'),
  function (p) { return p.getClientRects().length > 0; });
var pill = shown[0] || null;
var toggle = pill ? pill.nextElementSibling : null;
var header = document.querySelector('.topbar, .dz-topbar');
return {
  count: shown.length,
  pill: pill ? r(pill) : null,
  toggle: toggle && toggle.classList.contains('theme-toggle') ? r(toggle) : null,
  header: header ? r(header) : null,
  oldBar: document.querySelectorAll('.wd-update-banner, #wdUpdateBanner, #wdUpdateBadge').length,
  text: pill ? pill.textContent : null, title: pill ? pill.title : null,
  scrollW: document.documentElement.scrollWidth, viewport: [innerWidth, innerHeight]
};
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class TheUpdatePillSitsInTheHeader(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import server
        server.updater.detect_install.return_value = dict(INSTALL)
        server.updater.fetch_latest_release.return_value = dict(NEWER)
        cls._since = mock.patch.object(
            server.updater, "releases_since",
            return_value={"changes": [{"version": "9.0.9", "title": "Invented release",
                                       "notes": "## What changed\n- An invented line.",
                                       "url": ""}], "more": False})
        cls._since.start()

    @classmethod
    def tearDownClass(cls):
        cls._since.stop()
        super().tearDownClass()

    def load(self, drv, path):
        """The page, with no remembered answer, so its own check has to ask."""
        drv.get(self.base + "/")
        drv.execute_script("localStorage.removeItem(arguments[0]);", CACHE_KEY)
        drv.get(self.base + path)

    def pill_drawn(self, drv, path=None):
        if path == "/cloud":
            WebDriverWait(drv, 15).until(lambda d: d.execute_script(
                "return document.querySelectorAll('.wd-update-pill').length > 0;"))
            drv.execute_script(SHOW_CLOUD_HEADER)
        WebDriverWait(drv, 15).until(lambda d: d.execute_script(
            "return Array.prototype.some.call(document.querySelectorAll('.wd-update-pill'),"
            " function (p) { return p.getClientRects().length > 0; });"))
        return drv.execute_script(MEASURE)

    def test_a_pill_sits_against_the_theme_toggle_on_every_page(self):
        for kind, drv in self.each_browser():
            drv.set_window_size(1366, 768)
            for path in PAGES:
                with self.subTest(browser=kind, page=path):
                    self.load(drv, path)
                    m = self.pill_drawn(drv, path)
                    self.assertEqual(m["count"], 1, m)
                    self.assertEqual(m["text"], "Update", m)
                    self.assertIsNotNone(m["toggle"], "the pill must sit directly before the toggle: " + str(m))
                    # Against the toggle, on its row, and not wider than a pill.
                    self.assertLessEqual(m["pill"]["r"], m["toggle"]["l"] + 0.5, m)
                    self.assertLessEqual(m["toggle"]["l"] - m["pill"]["r"], 24, m)
                    mid = lambda b: (b["t"] + b["b"]) / 2
                    self.assertLess(abs(mid(m["pill"]) - mid(m["toggle"])), 6, m)
                    self.assertLessEqual(m["pill"]["w"], 120, m)
                    self.assertLessEqual(m["scrollW"], m["viewport"][0], m)

    def test_nothing_is_pushed_down_and_the_old_bar_and_badge_are_gone(self):
        for kind, drv in self.each_browser():
            drv.set_window_size(1366, 768)
            for path in PAGES:
                with self.subTest(browser=kind, page=path):
                    self.load(drv, path)
                    m = self.pill_drawn(drv, path)
                    self.assertEqual(m["oldBar"], 0, m)
                    self.assertLess(abs(m["header"]["t"]), 1, m)

    def test_the_hover_text_says_what_is_waiting(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.load(drv, "/")
                m = self.pill_drawn(drv)
                self.assertIn("v9.0.9", m["title"], m)

    def test_clicking_it_opens_about_with_the_update_card_marked(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                drv.set_window_size(1366, 768)
                self.load(drv, "/report")
                self.pill_drawn(drv)
                pill = [p for p in drv.find_elements(By.CSS_SELECTOR, ".wd-update-pill")
                        if p.is_displayed()][0]
                pill.click()
                WebDriverWait(drv, 15).until(lambda d: d.execute_script(
                    "var c = document.querySelector('#wdAboutModal.active .wd-about-update.is-newer');"
                    "return !!c && /9\\.0\\.9/.test(c.textContent);"))
                # Opening About starts its own check, and the button reads
                # "Checking..." until that finishes; read it once it is idle.
                WebDriverWait(drv, 15).until(lambda d: d.execute_script(
                    "var b = document.querySelector('#wdAboutModal .wd-about-checkBtn');"
                    "return !!b && !b.disabled;"))
                got = drv.execute_script(
                    "var c = document.querySelector('#wdAboutModal .wd-about-update');"
                    "var go = c.querySelector('.wd-update-goBtn');"
                    "return {title: c.querySelector('.wd-about-sectionTitle').textContent,"
                    " status: c.querySelector('.wd-about-updateResult').textContent,"
                    " go: go ? go.textContent : null,"
                    " check: c.querySelector('.wd-about-checkBtn').textContent};")
                # ascii(): the status line carries an arrow, and a failure
                # message with one cannot be printed on a cp1252 console.
                self.assertEqual(got["title"], "Updates", ascii(got))
                self.assertIn("Version 9.0.9 is available", got["status"], ascii(got))
                self.assertEqual(got["check"].strip(), "Check again", ascii(got))

    def test_the_update_button_names_the_version(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.load(drv, "/scale")
                self.pill_drawn(drv)
                [p for p in drv.find_elements(By.CSS_SELECTOR, ".wd-update-pill")
                 if p.is_displayed()][0].click()
                WebDriverWait(drv, 15).until(lambda d: d.execute_script(
                    "return !!document.querySelector('#wdAboutModal .wd-update-goBtn');"))
                label = drv.execute_script(
                    "return document.querySelector('#wdAboutModal .wd-update-goBtn').textContent;")
                self.assertEqual(label.strip(), "Update to v9.0.9")

    def test_a_current_install_has_no_pill_and_a_plain_card(self):
        import server
        server.updater.fetch_latest_release.return_value = dict(CURRENT)
        self.addCleanup(setattr, server.updater.fetch_latest_release,
                        "return_value", dict(NEWER))
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.load(drv, "/")
                WebDriverWait(drv, 15).until(lambda d: d.execute_script(
                    "return !!localStorage.getItem('wd-update-check');"))
                self.assertEqual(drv.execute_script(MEASURE)["count"], 0)
                drv.execute_script("window.wdOpenAbout();")
                WebDriverWait(drv, 15).until(lambda d: d.execute_script(
                    "return /latest release/.test(document.querySelector("
                    "'#wdAboutModal .wd-about-updateResult').textContent);"))
                self.assertFalse(drv.execute_script(
                    "return document.querySelector('#wdAboutModal .wd-about-update')"
                    ".classList.contains('is-newer');"))


if __name__ == "__main__":
    unittest.main()
