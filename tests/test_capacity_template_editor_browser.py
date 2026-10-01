"""Building, editing and defaulting a capacity template, in a real browser.

The run he described: build a template once from Ekahau's own profiles, make
it the default, and from then on a project opens with it already picked, so
it can be applied straight away. Driven through the real page with an
invented project; every assertion is on what the page shows or saved.
"""
from __future__ import annotations

import json
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

from tests.test_capacity_profiles import build_esx
from tests.test_squirrel_home_fits_the_screen import BrowserPagesHarness
from tests.test_strict_pages_work_in_a_browser import HAVE_SELENIUM

if HAVE_SELENIUM:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import Select, WebDriverWait


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class TheTemplateEditor(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.esx = Path(cls._tmp.name) / "invented-capacity.esx"
        build_esx(cls.esx)

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._tmp.cleanup()

    def settings(self):
        req = urllib.request.Request(
            self.base + "/api/settings/get", data=b"{}",
            headers={"Content-Type": "application/json", "X-WD-Wireless-Tools": "1"})
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode("utf-8"))["settings"]

    def open_project(self, drv):
        drv.set_window_size(1600, 1000)
        drv.get(self.base + "/capacity")
        WebDriverWait(drv, 15).until(lambda d: d.find_elements(By.ID, "fileInput"))
        drv.find_element(By.ID, "fileInput").send_keys(str(self.esx))
        WebDriverWait(drv, 20).until(
            lambda d: d.find_elements(By.CSS_SELECTOR, "#capTemplates .cap-tpl"))
        time.sleep(0.4)

    def chosen_name(self, drv):
        return drv.execute_script("""
          var on = document.querySelector('#capTemplates .cap-tpl[aria-checked="true"] .cap-tpl-name');
          return on ? on.firstChild.textContent.trim() : null;""")

    def build_one(self, drv, name):
        drv.find_element(By.ID, "capNewBtn").click()
        WebDriverWait(drv, 5).until(lambda d: d.execute_script(
            "return document.getElementById('capEditor').classList.contains('active');"))
        drv.find_element(By.ID, "capEdName").send_keys(name)
        rows = drv.find_elements(By.CSS_SELECTOR, "#capEdRows tr")
        self.assertEqual(len(rows), 1)
        per = rows[0].find_element(By.CSS_SELECTOR, "input[type=number]")
        per.clear()
        per.send_keys("2")
        drv.find_element(By.XPATH, "//button[contains(., 'Add a device')]").click()
        rows = drv.find_elements(By.CSS_SELECTOR, "#capEdRows tr")
        self.assertEqual(len(rows), 2)
        usage = Select(rows[1].find_elements(By.TAG_NAME, "select")[1])
        usage.select_by_index(len(usage.options) - 1)
        total = drv.find_element(By.ID, "capEdTotal").text
        self.assertIn("3 devices per person", total)
        drv.find_element(By.ID, "capEdSave").click()
        WebDriverWait(drv, 10).until(lambda d: not d.execute_script(
            "return document.getElementById('capEditor').classList.contains('active');"))
        time.sleep(0.4)

    def test_a_built_template_is_saved_chosen_and_can_be_the_default(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                name = "Invented office %s" % kind
                self.open_project(drv)
                self.build_one(drv, name)
                self.assertEqual(self.chosen_name(drv), name)
                view = drv.find_element(By.ID, "capTplView").text
                self.assertIn("per person", view.lower())
                drv.find_element(By.ID, "capMakeDefault").click()
                time.sleep(0.5)
                files = drv.execute_script(
                    "return Array.prototype.map.call(document.querySelectorAll("
                    "'#capTemplates .cap-tpl'), function (b) { return b.textContent; });")
                self.assertTrue(any(name in f and "default" in f for f in files), files)
                saved = self.settings()["capacity"]["default_template"]
                self.assertTrue(saved.endswith("_capacitytemplate.json"), saved)

                # Prep starts on the same template.
                drv.get(self.base + "/prep")
                WebDriverWait(drv, 15).until(lambda d: d.execute_script(
                    "var s = document.getElementById('prepCapTpl');"
                    "return !!(s && s.options.length > 1);"))
                WebDriverWait(drv, 10).until(lambda d: d.execute_script(
                    "return document.getElementById('prepCapTpl').value;") == saved)

                # A fresh open picks the default without a click.
                self.open_project(drv)
                self.assertEqual(self.chosen_name(drv), name)
                WebDriverWait(drv, 15).until(lambda d: d.find_element(
                    By.ID, "capApplyNote").text not in ("Pick a template first.", ""))

    def test_editing_the_shipped_example_saves_a_copy(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                self.open_project(drv)
                drv.execute_script("""
                  var b = Array.prototype.filter.call(
                    document.querySelectorAll('#capTemplates .cap-tpl'),
                    function (x) { return /example/.test(x.textContent); })[0];
                  b.click();""")
                time.sleep(0.3)
                drv.find_element(By.ID, "capEditBtn").click()
                name_box = drv.find_element(By.ID, "capEdName")
                self.assertIn("(my copy)", name_box.get_attribute("value"))
                name_box.clear()
                name_box.send_keys("Example copy %s" % kind)
                drv.find_element(By.ID, "capEdSave").click()
                time.sleep(0.8)
                texts = drv.execute_script(
                    "return Array.prototype.map.call(document.querySelectorAll("
                    "'#capTemplates .cap-tpl-name'), function (b) { return b.textContent; });")
                self.assertTrue(any("(example)" in t for t in texts), texts)
                self.assertTrue(any(("Example copy %s" % kind) in t for t in texts), texts)

    def test_delete_asks_by_naming_it_then_deletes(self):
        for kind, drv in self.each_browser():
            with self.subTest(browser=kind):
                name = "Throwaway %s" % kind
                self.open_project(drv)
                self.build_one(drv, name)
                btn = drv.find_element(By.ID, "capDeleteBtn")
                btn.click()
                self.assertIn(name, btn.text)
                btn.click()
                time.sleep(0.8)
                texts = drv.execute_script(
                    "return Array.prototype.map.call(document.querySelectorAll("
                    "'#capTemplates .cap-tpl-name'), function (b) { return b.textContent; });")
                self.assertFalse(any(name in t for t in texts), texts)


if __name__ == "__main__":
    unittest.main()
