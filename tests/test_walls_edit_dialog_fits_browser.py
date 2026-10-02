"""The wall-type editor fits a laptop screen and its controls read in full.

At 1366 wide the editor was four squeezed columns: "Stops short of the
ceiling" wrapped onto four lines, and at a laptop's height Cancel and Save sat
half below the window with nothing to scroll. The form now scrolls and the
footer stays put.

Driven through the real page with an invented project.
"""
from __future__ import annotations

import tempfile
import time
import unittest
from pathlib import Path

from tests.test_squirrel_home_fits_the_screen import BrowserPagesHarness
from tests.test_strict_pages_work_in_a_browser import HAVE_SELENIUM
from tests.test_walls_delete_names_drawn_walls_browser import _esx

if HAVE_SELENIUM:
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait

MEASURE = """
var save = document.getElementById('modalSaveBtn').getBoundingClientRect();
var modes = Array.prototype.map.call(document.querySelectorAll('.wt-vert-mode'),
  function (b) {
    var r = b.getBoundingClientRect();
    var lh = parseFloat(getComputedStyle(b).lineHeight) ||
             parseFloat(getComputedStyle(b).fontSize) * 1.3;
    return {h: r.height, lh: lh};
  });
return {saveTop: save.top, saveBottom: save.bottom, vh: innerHeight, modes: modes};
"""


@unittest.skipUnless(HAVE_SELENIUM, "selenium is not installed")
class TheWallTypeEditorFits(BrowserPagesHarness):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._tmp = tempfile.TemporaryDirectory()
        cls.esx = _esx(Path(cls._tmp.name) / "invented-edit.esx")

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._tmp.cleanup()

    def test_save_is_on_screen_and_the_height_choices_are_one_line(self):
        for kind, drv in self.each_browser():
            for w, h in ((1366, 768), (1366, 1080), (2519, 1279)):
                with self.subTest(browser=kind, size=(w, h)):
                    drv.set_window_size(w, h)
                    drv.get(self.base + "/walls")
                    WebDriverWait(drv, 15).until(
                        lambda d: d.find_elements(By.ID, "fileInput"))
                    drv.find_element(By.ID, "fileInput").send_keys(str(self.esx))
                    WebDriverWait(drv, 20).until(
                        lambda d: d.find_elements(By.CSS_SELECTOR, ".wall-card"))
                    drv.execute_script("openEditModal(0)")
                    time.sleep(0.5)
                    r = drv.execute_script(MEASURE)
                    self.assertGreaterEqual(r["saveTop"], 0, r)
                    self.assertLessEqual(r["saveBottom"], r["vh"], r)
                    self.assertEqual(len(r["modes"]), 2, r)
                    for m in r["modes"]:
                        self.assertLess(m["h"], m["lh"] * 2 + 24, r)


if __name__ == "__main__":
    unittest.main()
