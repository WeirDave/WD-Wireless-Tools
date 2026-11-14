"""The current-project chip, driven with real clicks in every browser.

Why a browser, and why clicks: the first version of the chip's menu was built on
the shared `.main-menu` class, and a global `focusin` handler closes any open
`.main-menu` when focus lands outside `.menu-wrap`. Pressing a button inside the
menu moves focus, so the menu closed on mouse-down and the click never arrived.
Calling `button.click()` from a script passed; a real click did nothing. So these
tests press the real controls and then look at what the page did.

The server is the real one, with a current project pointed at an invented,
deliberately imperfect `.esx` in a temp folder. Nothing here touches the real
`current_project.json`.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from tests.test_squirrel_home_fits_the_screen import BrowserPagesHarness
from tests.test_strict_pages_work_in_a_browser import HAVE_SELENIUM

if HAVE_SELENIUM:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

from tests import test_project_health as fixtures
from tools import current_project as cp

VISIBLE_CHIP = """
var chips = Array.prototype.filter.call(document.querySelectorAll('.wd-project-chip'),
  function (c) { return c.getClientRects().length > 0; });
return chips.length;
"""
GEOMETRY = """
var chip = Array.prototype.filter.call(document.querySelectorAll('.wd-project-chip'),
  function (c) { return c.getClientRects().length > 0; })[0];
var wrap = chip.parentNode, next = wrap.nextElementSibling;
var r = function (e) { var b = e.getBoundingClientRect(); return {l: b.left, r: b.right, t: b.top, b: b.bottom}; };
var pop = wrap.querySelector('.wd-project-pop');
return {chip: r(chip), next: next ? r(next) : null, nextClass: next ? next.className : '',
        text: chip.textContent, title: chip.title, hasProject: chip.classList.contains('has-project'),
        popOpen: pop.classList.contains('open'), popShown: pop.getClientRects().length > 0,
        scrollW: document.documentElement.scrollWidth, vw: innerWidth};
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class TheProjectChipWorksWithRealClicks(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp_dir = tempfile.TemporaryDirectory(prefix="wd-chip-")
        cls.tmp = Path(cls._tmp_dir.name)
        (cls.tmp / "projects").mkdir()
        cls.project = cls.tmp / "projects" / "Sample Warehouse.esx"
        cls.project.write_bytes(fixtures.imperfect())
        cls.other = cls.tmp / "projects" / "Sample Office.esx"
        cls.other.write_bytes(fixtures.clean())
        cls._store = mock.patch.object(
            cp, "store_path", lambda: cls.tmp / "store" / cp.STORE_NAME)
        cls._store.start()

    @classmethod
    def tearDownClass(cls):
        cls._store.stop()
        super().tearDownClass()
        cls._tmp_dir.cleanup()

    def reset(self):
        cp.clear()
        cp.set_current(self.other)
        cp.set_current(self.project)

    def load(self, drv, path):
        # Every browser starts from the same state: a test that runs once per
        # browser would otherwise hand the next one whatever the last one did.
        self.reset()
        drv.get(self.base + path)
        WebDriverWait(drv, 15).until(lambda d: d.execute_script(VISIBLE_CHIP) >= 1)
        WebDriverWait(drv, 15).until(lambda d: d.execute_script(
            "var c = document.querySelector('.wd-project-chip.has-project');"
            "return !!c;"))

    def chip(self, drv):
        return [c for c in drv.find_elements(By.CSS_SELECTOR, ".wd-project-chip")
                if c.is_displayed()][0]

    def open_menu(self, drv):
        self.chip(drv).click()
        WebDriverWait(drv, 10).until(lambda d: d.execute_script(GEOMETRY)["popShown"])

    def button(self, drv, what):
        return [b for b in drv.find_elements(By.CSS_SELECTOR, f"[data-pj='{what}']")
                if b.is_displayed()][0]

    def test_the_chip_names_the_project_and_sits_against_the_header_controls(self):
        for kind, drv in self.each_browser():
            drv.set_window_size(1366, 768)
            for path in ("/", "/walls", "/prep", "/report", "/capacity", "/plantrim", "/aprename"):
                with self.subTest(browser=kind, page=path):
                    self.load(drv, path)
                    g = drv.execute_script(GEOMETRY)
                    self.assertEqual("Sample Warehouse.esx", g["text"].strip(), g)
                    self.assertTrue(g["hasProject"], g)
                    self.assertIn("Sample Warehouse.esx", g["title"], g)
                    self.assertIsNotNone(g["next"], g)
                    self.assertLessEqual(g["chip"]["r"], g["next"]["l"] + 0.5,
                                         "the chip overlaps what follows it: %s" % g)
                    self.assertLessEqual(g["scrollW"], g["vw"], g)

    def test_a_real_click_opens_the_menu_and_a_real_click_inside_it_does_not_close_it(self):
        for kind, drv in self.each_browser():
            drv.set_window_size(1366, 768)
            with self.subTest(browser=kind):
                self.load(drv, "/walls")
                self.open_menu(drv)
                # Pressing "Check project" moves focus. The menu must survive
                # that long enough for the click to land.
                self.button(drv, "check").click()
                WebDriverWait(drv, 15).until(lambda d: d.execute_script(
                    "var m = document.getElementById('wdProjectCheck');"
                    "return !!m && m.classList.contains('active')"
                    " && m.querySelector('.wd-pf-body').textContent.indexOf('to fix') >= 0;"))
                body = drv.execute_script(
                    "return document.querySelector('#wdProjectCheck .wd-pf-body').innerText;")
                self.assertIn("Sample Warehouse.esx", body)
                self.assertIn("3 to fix", body)
                self.assertIn("Access points sharing a name", body)
                self.assertIn("Fix in AP Labeler", body)

    def test_the_check_closes_and_the_page_is_usable_again(self):
        for kind, drv in self.each_browser():
            drv.set_window_size(1366, 768)
            with self.subTest(browser=kind):
                self.load(drv, "/walls")
                self.open_menu(drv)
                self.button(drv, "check").click()
                WebDriverWait(drv, 15).until(lambda d: d.execute_script(
                    "return document.querySelector('#wdProjectCheck.active') !== null;"))
                drv.find_element(By.CSS_SELECTOR, "#wdProjectCheck .wd-pf-done").click()
                WebDriverWait(drv, 10).until(lambda d: d.execute_script(
                    "return document.querySelector('#wdProjectCheck.active') === null;"))

    def test_open_in_this_tool_opens_the_project_in_quick_walls(self):
        for kind, drv in self.each_browser():
            drv.set_window_size(1366, 768)
            with self.subTest(browser=kind):
                self.load(drv, "/walls")
                self.open_menu(drv)
                self.button(drv, "open").click()
                WebDriverWait(drv, 20).until(lambda d: d.execute_script(
                    "var e = document.getElementById('editor');"
                    "return !!e && e.classList.contains('active');"))

    def test_prep_checks_the_project_it_has_open(self):
        for kind, drv in self.each_browser():
            drv.set_window_size(1366, 768)
            with self.subTest(browser=kind):
                self.load(drv, "/prep")
                btn = drv.find_element(By.ID, "prepCheckBtn")
                self.assertFalse(btn.is_displayed(), "offered before a project is open")
                self.open_menu(drv)
                self.button(drv, "open").click()
                WebDriverWait(drv, 20).until(lambda d: d.find_element(
                    By.ID, "prepCheckBtn").is_displayed())
                drv.find_element(By.ID, "prepCheckBtn").click()
                WebDriverWait(drv, 15).until(lambda d: d.execute_script(
                    "var m = document.getElementById('wdProjectCheck');"
                    "return !!m && m.classList.contains('active')"
                    " && m.querySelector('.wd-pf-body').innerText.indexOf('to fix') >= 0;"))

    def test_a_page_with_no_way_to_open_a_project_does_not_offer_to(self):
        # The home page lists projects but has nothing to open one in.
        for kind, drv in self.each_browser():
            drv.set_window_size(1366, 768)
            with self.subTest(browser=kind):
                self.load(drv, "/")
                self.open_menu(drv)
                self.assertEqual([], [b for b in drv.find_elements(
                    By.CSS_SELECTOR, "[data-pj='open']") if b.is_displayed()])
                self.assertTrue(self.button(drv, "check"))

    def test_escape_and_a_click_elsewhere_close_the_menu(self):
        from selenium.webdriver.common.keys import Keys
        for kind, drv in self.each_browser():
            drv.set_window_size(1366, 768)
            with self.subTest(browser=kind):
                self.load(drv, "/walls")
                self.open_menu(drv)
                drv.find_element(By.TAG_NAME, "body").send_keys(Keys.ESCAPE)
                WebDriverWait(drv, 5).until(lambda d: not d.execute_script(GEOMETRY)["popOpen"])
                self.open_menu(drv)
                drv.execute_script("document.body.click();")
                WebDriverWait(drv, 5).until(lambda d: not d.execute_script(GEOMETRY)["popOpen"])

    def test_choosing_a_recent_project_makes_it_current(self):
        for kind, drv in self.each_browser():
            drv.set_window_size(1366, 768)
            with self.subTest(browser=kind):
                self.load(drv, "/walls")
                self.open_menu(drv)
                self.button(drv, "use").click()
                WebDriverWait(drv, 10).until(lambda d: d.execute_script(
                    GEOMETRY)["text"].strip() == "Sample Office.esx")
                self.assertEqual("Sample Office.esx", cp.current()["name"])

    def test_a_menu_that_cannot_fit_a_phone_still_fits_the_screen(self):
        for kind, drv in self.each_browser():
            drv.set_window_size(390, 800)
            with self.subTest(browser=kind):
                self.load(drv, "/prep")
                self.open_menu(drv)
                g = drv.execute_script(GEOMETRY)
                self.assertLessEqual(g["scrollW"], g["vw"], g)
                right = drv.execute_script(
                    "return document.querySelector('.wd-project-pop.open')"
                    ".getBoundingClientRect().right;")
                self.assertLessEqual(right, g["vw"] + 0.5)

    def test_clearing_the_list_forgets_everything(self):
        for kind, drv in self.each_browser():
            drv.set_window_size(1366, 768)
            with self.subTest(browser=kind):
                self.load(drv, "/walls")
                self.open_menu(drv)
                self.button(drv, "clear").click()
                WebDriverWait(drv, 10).until(lambda d: d.execute_script(
                    "return !document.querySelector('.wd-project-chip.has-project');"))
                self.assertIsNone(cp.current())
                self.assertEqual([], cp.recent())


if __name__ == "__main__":
    unittest.main()
