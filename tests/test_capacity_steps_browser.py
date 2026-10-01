"""Capacity's steps and templates respond when pressed, in a real browser.

"the side steps over there so my [cursor] turns into a pointer on the steps
... that doesn't do anything and you can't click on it". The rail only
scrolled, and on a tall window every card was already on screen, so a press
changed nothing visible. And the template to apply was a plain row in the
third card, which gave no sign it could be chosen.

Driven through the real app with an invented project: pressing a step marks
it current and outlines its card; the template list is the first card;
a lone template is picked and planned without a click.
"""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from tests.test_capacity_profiles import build_esx
from tests.test_squirrel_home_fits_the_screen import BrowserPagesHarness
from tests.test_strict_pages_work_in_a_browser import HAVE_SELENIUM

if HAVE_SELENIUM:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class CapacityStepsRespond(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.esx = Path(cls._tmp.name) / "invented-capacity.esx"
        build_esx(cls.esx)
        cls.bare = Path(cls._tmp.name) / "invented-no-profiles.esx"
        build_esx(cls.bare, with_capacity=False)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._tmp.cleanup()

    def open_project(self, drv):
        drv.set_window_size(2519, 1279)
        drv.get(self.base + "/capacity")
        WebDriverWait(drv, 15).until(
            lambda d: d.find_elements(By.ID, "fileInput"))
        drv.find_element(By.ID, "fileInput").send_keys(str(self.esx))
        WebDriverWait(drv, 20).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, "#capTemplates .cap-tpl"))
        time.sleep(0.3)

    def test_a_template_that_cannot_apply_says_where_the_reason_is(self):
        """A project without the template's profiles cannot take it. The
        footer used to say only "Nothing to apply." beside a greyed button,
        with the reason two screens up."""
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                drv.set_window_size(1366, 1000)
                drv.get(self.base + "/capacity")
                WebDriverWait(drv, 15).until(
                    lambda d: d.find_elements(By.ID, "fileInput"))
                drv.find_element(By.ID, "fileInput").send_keys(str(self.bare))
                WebDriverWait(drv, 20).until(lambda d: "does not have" in d.find_element(
                    By.ID, "capPlan").text)
                note = drv.find_element(By.ID, "capApplyNote").text
                self.assertIn("cannot be applied", note)
                self.assertIn("Apply it to this project", note)
                self.assertFalse(drv.find_element(By.ID, "capApplyBtn").is_enabled())

    def test_the_template_list_is_the_first_card(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_project(drv)
                first = drv.execute_script(
                    "return document.querySelector('.cap-wrap .cap-card').id;")
                self.assertEqual(first, "capStepTpl")

    def test_pressing_a_step_marks_it_and_outlines_its_card(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_project(drv)
                drv.find_element(
                    By.CSS_SELECTOR, '.pb-stage[data-step="capStep1"] button').click()
                time.sleep(0.2)
                r = drv.execute_script("""
                  return {
                    current: Array.prototype.map.call(
                      document.querySelectorAll('.pb-rail .pb-stage.is-current'),
                      function (s) { return s.getAttribute('data-step'); }),
                    flashed: document.getElementById('capStep1')
                               .classList.contains('is-flash')
                  };""")
                self.assertEqual(r["current"], ["capStep1"])
                self.assertTrue(r["flashed"], "the card gave no sign it was reached")

    def test_a_lone_template_is_picked_and_planned_without_a_click(self):
        """With only the shipped example there is nothing to choose between,
        so it is picked and planned the moment the project opens."""
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_project(drv)
                note = lambda: drv.find_element(By.ID, "capApplyNote").text
                WebDriverWait(drv, 15).until(
                    lambda d: note() not in ("Pick a template first.", ""))
                checked = drv.execute_script(
                    "return document.querySelector('#capTemplates .cap-tpl')"
                    ".getAttribute('aria-checked');")
                self.assertEqual(checked, "true")

if __name__ == "__main__":
    unittest.main()
